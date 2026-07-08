"""催收频率解析。把人写的 cadence 翻译成 JobQueue 能用的调度参数。

对应 SPEC.md 第8节：只对主攻目标催收；到点主动推送。
第一版支持两种最常用写法，解析不了就退回默认（每天20:00），并如实告知。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

# 中文数字 → 阿拉伯，覆盖 0~24（够表示小时/分钟口语）。
_CN_NUM = {
    "零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
    "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
    "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24,
}


def _cn_to_int(s: str) -> int | None:
    """把一段中文/阿拉伯数字转成整数。认不出返回 None。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    # "十X" / "二十X" 组合（十的位在表里已覆盖到二十四，这里兜底 X十Y 之类）
    if s.startswith("十") and s[1:] in _CN_NUM:
        return 10 + _CN_NUM[s[1:]]
    return None


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

# 口语每日：可选"每天"，可选时段词，N 点（中文或数字），可选"半"，可选"前/之前"。
# 例：每天晚上八点前 / 每天早上7点 / 晚上八点半
_DAILY_SPOKEN_RE = re.compile(
    r"(?:每天)?\s*(上午|早上|早晨|凌晨|中午|下午|傍晚|晚上|夜里)?\s*"
    r"([0-9]{1,2}|[一二两三四五六七八九十]+)\s*点\s*(半)?"
)
# 把时段词映射成"是否+12小时"。中午/上午类不加，下午/晚上类加 12。
_PM_PERIODS = {"下午", "傍晚", "晚上", "夜里"}
_AM_PERIODS = {"上午", "早上", "早晨", "凌晨", "中午"}


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

    # 口语每日：每天晚上八点前 / 早上7点半 等。放最后，前面精确/间隔都没命中才试。
    m = _DAILY_SPOKEN_RE.search(text)
    if m:
        period, hour_raw, half = m.group(1), m.group(2), m.group(3)
        h = _cn_to_int(hour_raw)
        if h is not None and 0 <= h <= 24:
            if period in _PM_PERIODS and h < 12:
                h += 12
            h = h % 24
            mi = 30 if half else 0
            label_period = period or ""
            return (
                DailySchedule(at=time(hour=h, minute=mi)),
                f"每天 {h:02d}:{mi:02d}（识别自「{label_period}{hour_raw}点{'半' if half else ''}」）",
            )

    return DailySchedule(at=time(hour=20, minute=0)), "每天 20:00（未识别你的写法，用了默认）"
