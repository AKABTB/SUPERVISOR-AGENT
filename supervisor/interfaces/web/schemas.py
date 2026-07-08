"""Web API 的请求/响应模型（Pydantic）。

交互层的数据壳，只做序列化，不含任何判断逻辑（守 SPEC 分层铁律）。
"""
from __future__ import annotations

from pydantic import BaseModel


# ---- 响应模型 ----

class GoalOut(BaseModel):
    id: int
    title: str
    is_primary: bool
    status: str
    cadence: str
    cadence_desc: str      # parse_cadence 的人类可读说明
    created_at: str
    deadline: str | None = None
    parent_id: int | None = None
    children: list["GoalOut"] = []      # 子目标（仅顶层目标会填）
    active_child_id: int | None = None  # 当前活跃子目标 id（催收落到它）


class PrimaryOut(BaseModel):
    """主攻目标卡片：目标 + 计数 + 最近判定。"""
    goal: GoalOut
    nagged: int
    delivered: int
    last_verdict: str | None = None


class StatsOut(BaseModel):
    active: int
    nagged_today: int
    delivered_this_week: int


class LogItem(BaseModel):
    kind: str              # "delivery" | "nag"
    at: str                # ISO 时间
    goal_id: int
    verdict: str | None = None      # delivery: pass/need_fix；nag: submitted/not_submitted
    text: str              # 展示文本


class OverviewOut(BaseModel):
    """控制台首屏：一把梭。"""
    bot_online: bool               # 仅表示"是否配了 token"，非跨进程探活
    primary: PrimaryOut | None
    queue: list[GoalOut]           # 排队中的（非主攻）active 目标
    stats: StatsOut
    logs: list[LogItem]


# ---- 请求模型 ----

class GoalCreate(BaseModel):
    title: str
    cadence: str = ""              # 空则走默认（每天20:00）


class GoalPatch(BaseModel):
    title: str | None = None
    cadence: str | None = None
