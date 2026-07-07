"""催收频率解析。把人写的 cadence 翻译成 JobQueue 能用的调度参数。

对应 SPEC.md 第8节：只对主攻目标催收；到点主动推送。
第一版支持两种最常用写法，解析不了就退回默认（每天20:00），并如实告知。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time


@dataclass
class DailySchedule:
    """每天固定时刻，如 每天20:00。"""
    at: time


@dataclass
class IntervalSchedule:
    """固定间隔，如 每2小时 / 每30分钟。单位：秒。"""
    seconds: int


Schedule = DailySchedule | IntervalSchedule

_DAILY_RE = re.compile(r"每天\s*(\d{1,2})[:：](\d{2})")
_HOUR_RE = re.compile(r"每\s*(\d+)\s*小时")
_MIN_RE = re.compile(r"每\s*(\d+)\s*分钟?")


def parse_cadence(cadence: str) -> tuple[Schedule, str]:
    """返回 (调度, 人类可读说明)。解析失败退回每天20:00。"""
    text = cadence.strip()

    m = _DAILY_RE.search(text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            return DailySchedule(at=time(hour=h, minute=mi)), f"每天 {h:02d}:{mi:02d}"

    m = _HOUR_RE.search(text)
    if m:
        n = int(m.group(1))
        if n > 0:
            return IntervalSchedule(seconds=n * 3600), f"每 {n} 小时"

    m = _MIN_RE.search(text)
    if m:
        n = int(m.group(1))
        if n > 0:
            return IntervalSchedule(seconds=n * 60), f"每 {n} 分钟"

    return DailySchedule(at=time(hour=20, minute=0)), "每天 20:00（未识别你的写法，用了默认）"
