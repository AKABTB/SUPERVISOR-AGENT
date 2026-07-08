"""Telegram Bot 交互层。对应 SPEC.md 第4节交互层。

分层铁律：这一层只管收发消息 + 认人 + 转调用，判断逻辑都在核心层。
步骤3：接入项目经理能力（定目标/主攻/列表/交掉）+ JobQueue 到点主动催收。
定目标走命令不走聊天 —— 防止滑回"陪你想清楚目标"的内耗。
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from telegram import BotCommand, ForceReply, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import Config
from ..core.goal_parser import parse_goal_nl
from ..core.intent import is_change_goal_intent
from ..core.project_manager import ProjectManager
from ..core.reviewer import Reviewer
from ..core.scheduler import DailySchedule, IntervalSchedule, parse_cadence
from ..llm import build_llm
from ..storage import Database

logger = logging.getLogger(__name__)

_NAG_JOB = "nag_primary"    # 催收 job 的统一名字，换主攻时先清旧再建新
_WATCH_JOB = "watch_db"     # 自校看门狗 job 的名字
_WATCH_INTERVAL = 20        # 自校间隔（秒）：Web/别处改了主攻或频率，这么久内 Bot 自动重挂

# 带参数的命令若被"光点菜单不打字"发来（TG 点击即发，拦不住），就回一条 ForceReply
# 提示、并在 user_data 里记下"在等哪个命令的参数"。下一条普通消息即当该命令参数处理。
_PENDING_KEY = "pending_cmd"

# 每个待补参数命令的 ForceReply 提示文案（贴催收调性）。
_PROMPTS = {
    "goal": "定啥？说人话：做什么 + 多久催你一次。\n例：我要每天晚上八点前交健身打卡。\n要拆步骤：重构登录，先写接口再接前端最后联调。\n（老格式也认：写完登录页 | 每天20:00）",
    "primary": "换哪个当主攻？发编号。/list 里的 # 后面那个数。",
    "done": "交掉哪个？发编号。",
    "change": "主攻改成啥？发新的目标定义。这是改目标唯一正门。",
}

# 命令菜单：让 TG 客户端显示 / 补全列表。描述贴催收人设，和 /start 文案一致。
# 顺序 = 菜单里的展示顺序，把最常用的放前面。
_COMMANDS = [
    BotCommand("goal", "定个目标，说人话即可，例：每天晚上八点前交健身打卡"),
    BotCommand("list", "看所有目标"),
    BotCommand("primary", "换当下主攻，用法：编号"),
    BotCommand("done", "交掉一个，别拖，用法：编号"),
    BotCommand("change", "改主攻定义（改目标唯一正门），用法：新目标"),
    BotCommand("nagnow", "立刻催我一次（测试用）"),
    BotCommand("start", "我是干嘛的 / 命令速查"),
    BotCommand("whoami", "看我的 chat_id"),
]


class SupervisorBot:
    def __init__(self, cfg: Config) -> None:
        if not cfg.telegram_token:
            raise ValueError("缺少 TELEGRAM_BOT_TOKEN —— 请在 .env 配置。")
        self._cfg = cfg
        self._owner_id: int | None = (
            int(cfg.telegram_owner_chat_id) if cfg.telegram_owner_chat_id else None
        )
        self._db = Database(cfg.db_path)
        self._pm = ProjectManager(self._db)
        self._llm = build_llm(cfg.llm)
        self._reviewer = Reviewer(self._db, self._llm)
        # 当前已挂催收 job 的"指纹"= (主攻id, cadence原文, 活跃子目标id)。看门狗拿它跟库
        # 对比，不一致说明别处（Web/其他）改了主攻/频率、或活跃子目标推进了 → 重挂。
        # None 表示当前没挂催收。
        self._nag_fingerprint: tuple[int, str, int | None] | None = None
        self._app = self._build_app(cfg)
        self._register()

    @staticmethod
    def _build_app(cfg: Config) -> Application:
        builder = Application.builder().token(cfg.telegram_token)
        if cfg.telegram_proxy:
            builder = builder.proxy(cfg.telegram_proxy).get_updates_proxy(cfg.telegram_proxy)
            logger.info("Telegram 走代理: %s", cfg.telegram_proxy)
        return builder.build()

    def _register(self) -> None:
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("whoami", self._on_whoami))
        self._app.add_handler(CommandHandler("goal", self._on_goal))
        self._app.add_handler(CommandHandler("primary", self._on_primary))
        self._app.add_handler(CommandHandler("list", self._on_list))
        self._app.add_handler(CommandHandler("done", self._on_done))
        self._app.add_handler(CommandHandler("change", self._on_change))
        self._app.add_handler(CommandHandler("nagnow", self._on_nagnow))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )
        # 启动后恢复已有主攻目标的催收（重启不丢催收）
        self._app.post_init = self._post_init

    def _is_owner(self, update: Update) -> bool:
        chat_id = update.effective_chat.id
        if self._owner_id is None:
            self._owner_id = chat_id
            logger.warning("owner 未配置，已自动绑定当前 chat_id=%s。", chat_id)
            return True
        return chat_id == self._owner_id

    # ---- 生命周期 ----

    async def _post_init(self, app: Application) -> None:
        """启动时若已有主攻目标，自动挂上催收 job；并挂上自校看门狗。"""
        # 把命令列表推给 Telegram 服务器 —— 客户端才会显示 / 菜单和输入补全。
        await app.bot.set_my_commands(_COMMANDS)
        logger.info("命令菜单已注册：%d 条。", len(_COMMANDS))
        self._reschedule_primary(app)
        # 看门狗：定时重读库，发现主攻/频率被别处（Web 等）改动就重挂催收。
        app.job_queue.run_repeating(
            self._watch_callback, interval=_WATCH_INTERVAL, first=_WATCH_INTERVAL,
            name=_WATCH_JOB,
        )
        logger.info("催收自校看门狗已挂：每 %d 秒重读库一次。", _WATCH_INTERVAL)

    async def _watch_callback(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """自校：当前库里的主攻(id, cadence, 活跃子目标id)若和已挂 job 的指纹不一致，就重挂。
        这样在 Web 或别处改了主攻/频率、或活跃子目标推进了，Bot 无需重启也会自动跟上。"""
        current = self._current_fingerprint()
        if current != self._nag_fingerprint:
            logger.info("自校发现变动：%s → %s，重挂催收。",
                        self._nag_fingerprint, current)
            self._reschedule_primary(ctx.application)

    def _current_fingerprint(self) -> tuple[int, str, int | None] | None:
        """当前库状态的催收指纹。活跃子目标推进也会变，触发看门狗重挂。"""
        target = self._pm.get_nag_target()
        if target is None:
            return None
        primary, active_child = target
        return (primary.id, primary.cadence, active_child.id if active_child else None)

    # ---- 催收调度 ----

    def _reschedule_primary(self, app: Application) -> None:
        """清掉旧催收 job，按当前主攻目标重挂。换主攻/交掉时调用。"""
        for job in app.job_queue.get_jobs_by_name(_NAG_JOB):
            job.schedule_removal()

        primary = self._pm.get_primary()
        if not primary or self._owner_id is None:
            logger.info("无主攻目标或无 owner，不挂催收。")
            self._nag_fingerprint = None
            return

        sched, desc = parse_cadence(primary.cadence)
        data = {"goal_id": primary.id}
        if isinstance(sched, DailySchedule):
            # 关键：给时刻附上本地时区，否则 APScheduler 按 UTC 理解，会差 8 小时。
            at_local = sched.at.replace(tzinfo=ZoneInfo(self._cfg.timezone))
            app.job_queue.run_daily(
                self._nag_callback, time=at_local, name=_NAG_JOB,
                chat_id=self._owner_id, data=data,
            )
        elif isinstance(sched, IntervalSchedule):
            app.job_queue.run_repeating(
                self._nag_callback, interval=sched.seconds, first=sched.seconds,
                name=_NAG_JOB, chat_id=self._owner_id, data=data,
            )
        # 记下这次挂的是什么，供看门狗对比（含活跃子目标 id）
        self._nag_fingerprint = self._current_fingerprint()
        logger.info("催收已挂：目标[%s] 频率=%s", primary.id, desc)

    async def _nag_callback(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """到点主动催收 —— 这是'官'落地、你躲不掉的那一刻。催词精确到活跃子目标。"""
        target = self._pm.get_nag_target()
        if target is None:
            return
        primary, active_child = target
        await ctx.bot.send_message(
            chat_id=ctx.job.chat_id, text=self._pm.nag_text(primary, active_child)
        )

    # ---- 命令 ----

    async def _ask(self, update, ctx, cmd: str) -> None:
        """带参命令被光点菜单发来（没带参数）时：回 ForceReply 提示、记下在等谁。
        ForceReply 会让 TG 客户端自动聚焦输入框、引用这条提示，等你打字。"""
        ctx.user_data[_PENDING_KEY] = cmd
        await update.message.reply_text(
            _PROMPTS[cmd], reply_markup=ForceReply(selective=True)
        )

    async def _on_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_owner(update):
            return
        await update.message.reply_text(
            "我在。我不是来陪你聊的，是来盯你交货的。\n\n"
            "定目标（走命令，不许在这跟我聊怎么定）：\n"
            "  /goal 说人话           例：/goal 每天晚上八点前交健身打卡\n"
            "                         拆步骤：/goal 重构登录，先写接口再接前端最后联调\n"
            "  /primary 编号          换当下主攻\n"
            "  /list                  看所有目标\n"
            "  /done 编号             交掉一个（或交掉当前子步骤）\n"
            "  /nagnow                立刻催我一次（测试用）\n\n"
            "频率写法：每天20:00 / 每天晚上八点 / 每2小时 / 每30分钟。\n"
            "只对主攻目标催收，其他排队；拆了步骤只催当前那一步。"
        )

    async def _on_whoami(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(f"chat_id = {update.effective_chat.id}")

    async def _on_goal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_owner(update):
            return
        raw = " ".join(ctx.args).strip()
        if not raw:  # 光点菜单没打字 → 弹提示等下一条
            await self._ask(update, ctx, "goal")
            return
        await self._do_goal(update, ctx, raw)

    async def _do_goal(self, update, ctx, raw: str) -> None:
        raw = raw.strip()
        if not raw:
            await self._goal_format_hint(update)
            return

        # 含竖线 = 用户明确用了老格式 → 直接切，不劳 LLM。
        if "|" in raw or "｜" in raw:
            title, cadence = _split_goal(raw)
            if not title:
                await self._goal_format_hint(update)
                return
            goal, is_primary = self._pm.add_goal(title, cadence)
            await self._announce_goal(update, ctx, goal, [], is_primary)
            return

        # 否则当自然语言：送 LLM 解析出 标题/频率/截止/子目标。
        parsed = await _run_parse(self._llm, raw)
        if not parsed.confident:
            # 拆不准 —— 反问确认，绝不瞎猜落库（守灵魂：不帮你想目标）。
            ctx.user_data[_PENDING_KEY] = "goal"
            await update.message.reply_text(
                "没听清你到底要交什么东西。一句话说清「做什么 + 多久催你一次」。\n"
                "例：我要每天晚上八点前交健身打卡。\n"
                "要拆步骤就直说：重构登录，先写接口再接前端最后联调。",
                reply_markup=ForceReply(selective=True),
            )
            return

        parent, children, is_primary = self._pm.add_goal_tree(parsed)
        await self._announce_goal(update, ctx, parent, children, is_primary)

    async def _goal_format_hint(self, update) -> None:
        await update.message.reply_text(
            "直接说人话就行：做什么 + 多久催你一次。\n"
            "例：我要每天晚上八点前交健身打卡。\n"
            "要拆步骤：重构登录，先写接口再接前端最后联调。\n"
            "老格式也认：写完登录页 | 每天20:00。\n"
            "目标要小到今天就能出体。"
        )

    async def _announce_goal(self, update, ctx, goal, children, is_primary: bool) -> None:
        """落库后统一回执 + 重挂催收。children 非空则列出子目标。"""
        _, desc = parse_cadence(goal.cadence)
        self._reschedule_primary(ctx.application)
        tag = "【当下主攻】" if is_primary else "（排队中，不催；用 /primary 提为主攻）"
        lines = [f"记下了。#{goal.id} {goal.title} {tag}"]
        if children:
            lines.append("拆成：")
            lines.extend(f"  {i}. {c.title}" for i, c in enumerate(children, 1))
            lines.append(f"催收：{desc}（先盯第一步：{children[0].title}）")
        else:
            lines.append(f"催收：{desc}")
        lines.append("到点我会来要东西。")
        await update.message.reply_text("\n".join(lines))

    async def _on_primary(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_owner(update):
            return
        if not ctx.args:  # 光点菜单没打字 → 弹提示等下一条
            await self._ask(update, ctx, "primary")
            return
        await self._do_primary(update, ctx, " ".join(ctx.args).strip())

    async def _do_primary(self, update, ctx, arg: str) -> None:
        if not arg.isdigit():
            await update.message.reply_text("发个编号（纯数字）。/list 看看。")
            return
        primary = self._pm.set_primary(int(arg))
        if not primary:
            await update.message.reply_text("没这个进行中的目标。/list 看看。")
            return
        self._reschedule_primary(ctx.application)
        _, desc = parse_cadence(primary.cadence)
        await update.message.reply_text(
            f"主攻换成 #{primary.id} {primary.title}。催收：{desc}。其他排队。"
        )

    async def _on_list(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_owner(update):
            return
        goals = self._pm.list_active()
        if not goals:
            await update.message.reply_text("没有进行中的目标。/goal 定一个。")
            return
        lines = []
        for g in goals:
            _, desc = parse_cadence(g.cadence)
            star = "★主攻" if g.is_primary else "  排队"
            lines.append(f"#{g.id} [{star}] {g.title}  ({desc})")
            # 有子目标就缩进列出，标出当前活跃那步
            children = self._db.list_children(g.id)
            if children:
                active = self._db.get_active_child(g.id)
                for c in children:
                    mark = "▶" if (active and c.id == active.id) else (
                        "✓" if c.status.value == "done" else "·")
                    lines.append(f"      {mark} #{c.id} {c.title}")
        await update.message.reply_text("\n".join(lines))

    async def _on_done(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_owner(update):
            return
        if not ctx.args:  # 光点菜单没打字 → 弹提示等下一条
            await self._ask(update, ctx, "done")
            return
        await self._do_done(update, ctx, " ".join(ctx.args).strip())

    async def _do_done(self, update, ctx, arg: str) -> None:
        if not arg.isdigit():
            await update.message.reply_text("发个编号（纯数字）。")
            return
        goal = self._pm.mark_done(int(arg))
        if not goal:
            await update.message.reply_text("没这个目标。")
            return
        self._reschedule_primary(ctx.application)
        await update.message.reply_text(f"#{goal.id} {goal.title} 交掉了。下一个。")

    async def _on_change(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """走正门改主攻目标定义。这是'二次确认' —— 郑重发命令才放行。"""
        if not self._is_owner(update):
            return
        if not ctx.args:  # 光点菜单没打字 → 弹提示等下一条
            await self._ask(update, ctx, "change")
            return
        await self._do_change(update, ctx, " ".join(ctx.args).strip())

    async def _do_change(self, update, ctx, new_title: str) -> None:
        goal = self._pm.change_primary_title(new_title)
        if not goal:
            await update.message.reply_text("现在没有主攻目标可改。先 /goal 定一个。")
            return
        await update.message.reply_text(
            f"改了。主攻现在是：#{goal.id} {goal.title}\n"
            f"锁定。别再改。东西呢？"
        )

    async def _on_nagnow(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_owner(update):
            return
        target = self._pm.get_nag_target()
        if target is None:
            await update.message.reply_text(self._pm.no_primary_text())
            return
        primary, active_child = target
        await update.message.reply_text(self._pm.nag_text(primary, active_child))

    async def _on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_owner(update):
            return

        text = update.message.text.strip()

        # 先看是不是在补某个带参命令的参数（上一步点菜单没打字，Bot 发了 ForceReply）。
        # 是 → 当那个命令的参数处理，处理完清掉标记，不走下面的交货审查。
        pending = ctx.user_data.pop(_PENDING_KEY, None)
        if pending == "goal":
            await self._do_goal(update, ctx, text)
            return
        if pending == "primary":
            await self._do_primary(update, ctx, text)
            return
        if pending == "done":
            await self._do_done(update, ctx, text)
            return
        if pending == "change":
            await self._do_change(update, ctx, text)
            return

        target = self._pm.get_nag_target()
        if target is None:
            await update.message.reply_text(self._pm.no_primary_text())
            return
        primary, active_child = target
        # 交货/审查落到"当前该盯的那个"：有活跃子目标就是子目标，否则是大目标本身。
        review_goal = active_child or primary

        # 拦改：先看你是不是想改目标定义（善变的老板）。是 → 硬拦，指向正门。
        wants_change = await _run_intent(self._llm, text)
        if wants_change:
            await update.message.reply_text(
                "这不在锁定的需求里。想改目标？走正门：\n"
                f"  /change 新目标\n"
                f"随口在这改，我不认。现在盯的还是：「{review_goal.title}」。东西呢？"
            )
            return

        # 否则一律当"交货尝试"送审查官 —— 审查官自己会戳穿空话。
        await update.message.reply_text(f"收货，审「{review_goal.title}」……")
        _verdict, _issues, reply = await _run_review(
            self._reviewer, review_goal, text
        )
        await update.message.reply_text(reply)

    def run(self) -> None:
        logger.info("SupervisorBot 启动，开始 polling……")
        self._app.run_polling()


async def _run_review(reviewer: Reviewer, goal, submission: str):
    """审查是同步阻塞（调 LLM），丢到默认线程池执行，不卡事件循环。"""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, reviewer.review, goal, submission)


async def _run_intent(llm, text: str) -> bool:
    """意图识别也调 LLM，同样丢线程池。"""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, is_change_goal_intent, llm, text)


async def _run_parse(llm, text: str):
    """自然语言目标解析也调 LLM，丢线程池，不卡事件循环。"""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, parse_goal_nl, llm, text)


def _split_goal(raw: str) -> tuple[str, str]:
    """把 '/goal' 后面的文字切成 (目标, 频率)。手机上怎么打都尽量认。

    优先级：竖线(全/半角) > "每…"频率关键字 > 整句当目标(频率留空走默认)。
    返回 title 为空表示啥都没给。
    """
    raw = raw.strip()
    if not raw:
        return "", ""

    # 1) 竖线分隔：| 或 ｜
    for sep in ("|", "｜"):
        if sep in raw:
            title, cadence = raw.split(sep, 1)
            return title.strip(), cadence.strip()

    # 2) 无竖线：从"每"字处切（"每天/每N小时/每N分钟"）
    idx = raw.rfind("每")
    if idx > 0:  # 每前面得有内容当目标
        return raw[:idx].strip(), raw[idx:].strip()

    # 3) 整句当目标，频率留空 → add_goal 里走默认(每天20:00)
    return raw, ""
