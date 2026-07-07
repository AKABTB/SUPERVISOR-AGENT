"""项目经理（能力二·进度调控）。对应 SPEC.md 第7节能力二 + 第8节催收调度。

铁律：只认进度、只认"到点交货没有"。极硬、极直接。
定目标走命令不走聊天 —— 自由聊天定目标会滑回"陪你想清楚"的内耗陷阱。
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..storage import Database, Goal, GoalStatus


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
        goal = next(g for g in self._db.list_goals() if g.id == goal_id)
        return goal, make_primary

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

    def change_primary_title(self, new_title: str) -> Goal | None:
        """走正门改主攻目标的定义（/change 二次确认后才调）。无主攻返回 None。"""
        primary = self._db.get_primary()
        if not primary:
            return None
        self._db.set_goal_title(primary.id, new_title.strip())
        return self._db.get_primary()

    def mark_done(self, goal_id: int) -> Goal | None:
        goals = {g.id: g for g in self._db.list_goals()}
        if goal_id not in goals:
            return None
        self._db.set_goal_status(goal_id, GoalStatus.DONE)
        # 若交掉的是主攻，把队列里下一个 active 顶上来当主攻
        remaining = self._db.list_goals(status=GoalStatus.ACTIVE)
        if remaining and self._db.get_primary() is None:
            self._db.set_primary(remaining[0].id)
        return goals[goal_id]

    # ---- 催收话术（赤裸、只问东西呢）----

    @staticmethod
    def nag_text(goal: Goal) -> str:
        return (
            f"「{goal.title}」的东西呢？交了没有。\n"
            f"只认两种回答：交了（把产出发我）/ 没交。\n"
            f"“在做了 / 快好了 / 卡住了 / 最近忙” 一律等于没交。"
        )

    @staticmethod
    def no_primary_text() -> str:
        return "现在没有主攻目标。用 /goal 定一个，小到今天就能出体的那种。"
