"""项目经理（能力二·进度调控）。对应 SPEC.md 第7节能力二 + 第8节催收调度。

铁律：只认进度、只认"到点交货没有"。极硬、极直接。
定目标走命令不走聊天 —— 自由聊天定目标会滑回"陪你想清楚"的内耗陷阱。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..storage import Database, Goal, GoalStatus
from .goal_parser import ParsedGoal


class ProjectManager:
    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ---- 目标管理 ----

    def add_goal(self, title: str, cadence: str) -> tuple[Goal, bool]:
        """加目标。若当前无主攻，新目标自动设为主攻。返回 (目标, 是否成为主攻)。"""
        title = title.strip()
        cadence = cadence.strip() or "每天20:00"
        has_primary = self._db.get_primary() is not None
        make_primary = not has_primary
        goal_id = self._db.add_goal(
            title=title, cadence=cadence, created_at=self._now(),
            is_primary=make_primary,
        )
        goal = self._db.get_goal(goal_id)
        return goal, make_primary

    def add_goal_tree(self, parsed: ParsedGoal) -> tuple[Goal, list[Goal], bool]:
        """按解析结果落一个目标（含可选子目标）。返回 (大目标, 子目标列表, 是否成为主攻)。

        子目标继承大目标的 cadence，不单独当主攻、不单独催——催收落到"活跃子目标"。
        """
        cadence = parsed.cadence.strip() or "每天20:00"
        parent, is_primary = self.add_goal(parsed.title, cadence)
        children: list[Goal] = []
        for sub_title in parsed.subgoals:
            sub_title = sub_title.strip()
            if not sub_title:
                continue
            sub_id = self._db.add_goal(
                title=sub_title, cadence=cadence, created_at=self._now(),
                is_primary=False, parent_id=parent.id,
            )
            child = self._db.get_goal(sub_id)
            if child:
                children.append(child)
        return parent, children, is_primary

    def set_primary(self, goal_id: int) -> Goal | None:
        goals = {g.id: g for g in self._db.list_goals(status=GoalStatus.ACTIVE)}
        if goal_id not in goals:
            return None
        self._db.set_primary(goal_id)
        return self._db.get_primary()

    def list_active(self) -> list[Goal]:
        return self._db.list_goals(status=GoalStatus.ACTIVE)

    def get_primary(self) -> Goal | None:
        return self._db.get_primary()

    def get_nag_target(self) -> tuple[Goal, Goal | None] | None:
        """催收/审查该盯谁。返回 (主攻大目标, 活跃子目标|None)。无主攻返回 None。

        - 大目标没拆子目标 → (大目标, None)，退化成老行为，催/审大目标本身。
        - 拆了子目标 → (大目标, 当前活跃子目标)，催收话术精确到子目标，交货审子目标。
        - 子目标全交完但大目标还 active → (大目标, None)，催大目标收尾/交掉。
        """
        primary = self._db.get_primary()
        if not primary:
            return None
        active_child = self._db.get_active_child(primary.id)
        return primary, active_child

    def change_primary_title(self, new_title: str) -> Goal | None:
        """走正门改主攻目标的定义（/change 二次确认后才调）。无主攻返回 None。"""
        primary = self._db.get_primary()
        if not primary:
            return None
        self._db.set_goal_title(primary.id, new_title.strip())
        return self._db.get_primary()

    def mark_done(self, goal_id: int) -> Goal | None:
        goal = self._db.get_goal(goal_id)
        if goal is None:
            return None
        self._db.set_goal_status(goal_id, GoalStatus.DONE)

        # 交掉的是子目标：不动主攻。下一个活跃子目标由 get_active_child 天然顶上。
        if goal.parent_id is not None:
            return goal

        # 交掉的是顶层大目标：若它是主攻，把队列里下一个顶层 active 顶上来当主攻。
        remaining = self._db.list_goals(status=GoalStatus.ACTIVE)  # 默认只顶层
        if remaining and self._db.get_primary() is None:
            self._db.set_primary(remaining[0].id)
        return goal

    # ---- 催收话术（赤裸、只问东西呢）----

    @staticmethod
    def nag_text(goal: Goal, active_child: Goal | None = None) -> str:
        """催收话术。有活跃子目标时精确到「大目标 · 子目标」。"""
        if active_child is not None:
            subject = f"{goal.title} · {active_child.title}"
        else:
            subject = goal.title
        return (
            f"「{subject}」的东西呢？交了没有。\n"
            f"只认两种回答：交了（把产出发我）/ 没交。\n"
            f"“在做了 / 快好了 / 卡住了 / 最近忙” 一律等于没交。"
        )

    @staticmethod
    def no_primary_text() -> str:
        return "现在没有主攻目标。用 /goal 定一个，小到今天就能出体的那种。"
