"""统一入口。
    python -m supervisor          有 token → 启动 Bot；无 token → 跑骨架自检
    python -m supervisor web      启动 Web 控制台（清醒管理者面板）
    python -m supervisor selfcheck 强制只跑自检
对应 SPEC.md 步骤0/2 交货验证 + 第9节 Web 面板。
"""
from __future__ import annotations

import logging
import sys

from .config import load_config
from .storage import Database, GoalStatus


def selfcheck(cfg) -> None:
    print("[config] llm.provider =", cfg.llm.provider, "| model =", cfg.llm.model)
    print("[config] db_path =", cfg.db_path)
    print("[config] timezone =", cfg.timezone)
    print("[config] telegram token 已配置:", bool(cfg.telegram_token))

    db = Database(cfg.db_path)
    print("[db] 建表完成，data.db 就绪")
    goals = db.list_goals(status=GoalStatus.ACTIVE)
    print(f"[db] 当前进行中目标数: {len(goals)}")
    print("\n[OK] 骨架自检通过。")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()

    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck(cfg)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "web":
        from .interfaces.web import run_web
        run_web(cfg, host=cfg.web_host, port=cfg.web_port)
        return

    if not cfg.telegram_token:
        print("[!] 未配置 TELEGRAM_BOT_TOKEN，退回骨架自检。")
        print("    去 @BotFather 拿 token 后填入 .env，即可 `python -m supervisor` 启动 Bot。\n")
        selfcheck(cfg)
        return

    from .interfaces import SupervisorBot
    SupervisorBot(cfg).run()


if __name__ == "__main__":
    main()
