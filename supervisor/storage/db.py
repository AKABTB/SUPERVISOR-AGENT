"""SQLite 存储层。建表 + 数据访问。对应 SPEC.md 第5、6节。

分层铁律：这一层只管存取，不含任何催收/审查/人格逻辑。
今天 TG 读它、明天 Web 读同一份 —— 所以这里保持纯净。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from .models import (
    CountedAs,
    DeliveryLog,
    Goal,
    GoalStatus,
    NagLog,
    Verdict,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active',
    cadence     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    deadline    TEXT,
    parent_id   INTEGER REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS delivery_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id       INTEGER NOT NULL REFERENCES goals(id),
    submitted_at  TEXT NOT NULL,
    content       TEXT NOT NULL,
    review        TEXT NOT NULL DEFAULT '',
    verdict       TEXT NOT NULL DEFAULT 'need_fix'
);

CREATE TABLE IF NOT EXISTS nag_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id     INTEGER NOT NULL REFERENCES goals(id),
    nagged_at   TEXT NOT NULL,
    your_reply  TEXT NOT NULL DEFAULT '',
    counted_as  TEXT NOT NULL DEFAULT 'not_submitted'
);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn) -> None:
        """幂等迁移。老库（无 parent_id 列）自动补列，不炸现有 data.db。
        Bot 和 Web 两进程共用一份库，两边都会走这里，必须能反复安全执行。"""
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(goals);").fetchall()}
        if "parent_id" not in cols:
            conn.execute("ALTER TABLE goals ADD COLUMN parent_id INTEGER REFERENCES goals(id);")

    # ---- Goal ----

    def add_goal(self, title: str, cadence: str, created_at: str,
                 is_primary: bool = False, deadline: str | None = None,
                 parent_id: int | None = None) -> int:
        with self._conn() as conn:
            if is_primary:
                conn.execute("UPDATE goals SET is_primary = 0 WHERE is_primary = 1;")
            cur = conn.execute(
                "INSERT INTO goals (title, is_primary, status, cadence, created_at, deadline, parent_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?);",
                (title, int(is_primary), GoalStatus.ACTIVE.value, cadence, created_at,
                 deadline, parent_id),
            )
            return int(cur.lastrowid)

    def set_primary(self, goal_id: int) -> None:
        """标当下主攻。全局至多一个 —— 先清空再设。"""
        with self._conn() as conn:
            conn.execute("UPDATE goals SET is_primary = 0 WHERE is_primary = 1;")
            conn.execute("UPDATE goals SET is_primary = 1 WHERE id = ?;", (goal_id,))

    def get_primary(self) -> Goal | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE is_primary = 1 AND status = 'active' LIMIT 1;"
            ).fetchone()
            return _row_to_goal(row) if row else None

    def list_goals(self, status: GoalStatus | None = None,
                   top_level_only: bool = True) -> list[Goal]:
        """默认只列顶层大目标（parent_id IS NULL）——子目标不进目标列表/队列/主攻。
        需要含子目标时传 top_level_only=False。"""
        where = []
        params: list = []
        if status:
            where.append("status = ?")
            params.append(status.value)
        if top_level_only:
            where.append("parent_id IS NULL")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM goals{clause} ORDER BY is_primary DESC, id;", params
            ).fetchall()
            return [_row_to_goal(r) for r in rows]

    def set_goal_status(self, goal_id: int, status: GoalStatus) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE goals SET status = ? WHERE id = ?;", (status.value, goal_id)
            )

    def set_goal_title(self, goal_id: int, title: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE goals SET title = ? WHERE id = ?;", (title, goal_id)
            )

    def set_goal_cadence(self, goal_id: int, cadence: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE goals SET cadence = ? WHERE id = ?;", (cadence, goal_id)
            )

    def get_goal(self, goal_id: int) -> Goal | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE id = ?;", (goal_id,)
            ).fetchone()
            return _row_to_goal(row) if row else None

    # ---- 层级（父子目标） ----

    def list_children(self, parent_id: int,
                      status: GoalStatus | None = None) -> list[Goal]:
        """列某大目标的子目标，按 id 升序（= 创建/推进顺序）。"""
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM goals WHERE parent_id = ? AND status = ? ORDER BY id;",
                    (parent_id, status.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM goals WHERE parent_id = ? ORDER BY id;",
                    (parent_id,),
                ).fetchall()
            return [_row_to_goal(r) for r in rows]

    def get_active_child(self, parent_id: int) -> Goal | None:
        """取该大目标下"当前活跃"的子目标 = 第一个 active 子（按 id）。
        催收就落到它身上。无 active 子则返回 None（子全交完或本就没拆）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE parent_id = ? AND status = 'active' "
                "ORDER BY id LIMIT 1;",
                (parent_id,),
            ).fetchone()
            return _row_to_goal(row) if row else None

    def has_children(self, parent_id: int) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM goals WHERE parent_id = ? LIMIT 1;", (parent_id,)
            ).fetchone()
            return row is not None

    # ---- DeliveryLog ----

    def add_delivery(self, goal_id: int, submitted_at: str, content: str,
                     review: str, verdict: Verdict) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO delivery_logs (goal_id, submitted_at, content, review, verdict) "
                "VALUES (?, ?, ?, ?, ?);",
                (goal_id, submitted_at, content, review, verdict.value),
            )
            return int(cur.lastrowid)

    def list_deliveries(self, goal_id: int | None = None,
                        limit: int = 50) -> list[DeliveryLog]:
        with self._conn() as conn:
            if goal_id is not None:
                rows = conn.execute(
                    "SELECT * FROM delivery_logs WHERE goal_id = ? "
                    "ORDER BY id DESC LIMIT ?;",
                    (goal_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM delivery_logs ORDER BY id DESC LIMIT ?;",
                    (limit,),
                ).fetchall()
            return [_row_to_delivery(r) for r in rows]

    # ---- NagLog ----

    def add_nag(self, goal_id: int, nagged_at: str, your_reply: str,
                counted_as: CountedAs) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO nag_logs (goal_id, nagged_at, your_reply, counted_as) "
                "VALUES (?, ?, ?, ?);",
                (goal_id, nagged_at, your_reply, counted_as.value),
            )
            return int(cur.lastrowid)

    def list_nags(self, goal_id: int | None = None,
                  limit: int = 50) -> list[NagLog]:
        with self._conn() as conn:
            if goal_id is not None:
                rows = conn.execute(
                    "SELECT * FROM nag_logs WHERE goal_id = ? "
                    "ORDER BY id DESC LIMIT ?;",
                    (goal_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nag_logs ORDER BY id DESC LIMIT ?;",
                    (limit,),
                ).fetchall()
            return [_row_to_nag(r) for r in rows]

    # ---- 统计（供 Web 控制台首屏） ----

    def count_active(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM goals WHERE status = 'active';"
            ).fetchone()
            return int(row["n"])

    def count_nags_since(self, since_iso: str) -> int:
        """自某 ISO 时刻起的催收条数（用于'今日催收'）。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM nag_logs WHERE nagged_at >= ?;",
                (since_iso,),
            ).fetchone()
            return int(row["n"])

    def count_deliveries_since(self, since_iso: str,
                               verdict: Verdict | None = None) -> int:
        """自某 ISO 时刻起的交货条数（可按 verdict 过滤，用于'本周交付'）。"""
        with self._conn() as conn:
            if verdict is not None:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM delivery_logs "
                    "WHERE submitted_at >= ? AND verdict = ?;",
                    (since_iso, verdict.value),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM delivery_logs WHERE submitted_at >= ?;",
                    (since_iso,),
                ).fetchone()
            return int(row["n"])

    def goal_counters(self, goal_id: int) -> tuple[int, int]:
        """返回 (催收次数, 交货次数)。用于主攻目标卡片。"""
        with self._conn() as conn:
            nags = conn.execute(
                "SELECT COUNT(*) AS n FROM nag_logs WHERE goal_id = ?;", (goal_id,)
            ).fetchone()["n"]
            dels = conn.execute(
                "SELECT COUNT(*) AS n FROM delivery_logs WHERE goal_id = ?;", (goal_id,)
            ).fetchone()["n"]
            return int(nags), int(dels)

    def last_verdict(self, goal_id: int) -> Verdict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT verdict FROM delivery_logs WHERE goal_id = ? "
                "ORDER BY id DESC LIMIT 1;",
                (goal_id,),
            ).fetchone()
            return Verdict(row["verdict"]) if row else None


def _row_to_goal(row: sqlite3.Row) -> Goal:
    keys = row.keys()
    return Goal(
        id=row["id"],
        title=row["title"],
        is_primary=bool(row["is_primary"]),
        status=GoalStatus(row["status"]),
        cadence=row["cadence"],
        created_at=row["created_at"],
        deadline=row["deadline"],
        parent_id=row["parent_id"] if "parent_id" in keys else None,
    )


def _row_to_delivery(row: sqlite3.Row) -> DeliveryLog:
    return DeliveryLog(
        id=row["id"],
        goal_id=row["goal_id"],
        submitted_at=row["submitted_at"],
        content=row["content"],
        review=row["review"],
        verdict=Verdict(row["verdict"]),
    )


def _row_to_nag(row: sqlite3.Row) -> NagLog:
    return NagLog(
        id=row["id"],
        goal_id=row["goal_id"],
        nagged_at=row["nagged_at"],
        your_reply=row["your_reply"],
        counted_as=CountedAs(row["counted_as"]),
    )
