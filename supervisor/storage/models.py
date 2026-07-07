"""数据结构定义。对应 SPEC.md 第6节。

为未来 Web 预留：这些是纯数据对象，不含任何 TG / LLM 逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GoalStatus(str, Enum):
    ACTIVE = "active"        # 进行中
    DONE = "done"            # 已交
    ARCHIVED = "archived"    # 归档


class Verdict(str, Enum):
    PASS = "pass"
    NEED_FIX = "need_fix"


class CountedAs(str, Enum):
    SUBMITTED = "submitted"          # 交了
    NOT_SUBMITTED = "not_submitted"  # 没交（含一切借口）


@dataclass
class Goal:
    """目标 / 项目。要求：小到'今天能出体'。"""
    id: int | None
    title: str
    is_primary: bool          # 是否当下主攻（全局至多一个 True）
    status: GoalStatus
    cadence: str              # 催收频率，如 "每天20:00"
    created_at: str
    deadline: str | None = None


@dataclass
class DeliveryLog:
    """交货记录。"""
    id: int | None
    goal_id: int
    submitted_at: str
    content: str              # 自报产出（文字/文件路径/链接）
    review: str               # 审查官挑刺结论
    verdict: Verdict


@dataclass
class NagLog:
    """催收记录。"""
    id: int | None
    goal_id: int
    nagged_at: str
    your_reply: str
    counted_as: CountedAs
