"""自然语言目标解析（需求1 + 需求3的入口）。对应 BACKLOG #1 / #3。

把用户一句人话翻译成结构化目标：标题 + 频率 + 截止，以及可选的子目标列表。
这是"翻译输入"，不是"帮你想目标"——守 SPEC 第0节灵魂：
- 只从用户已经说出口的话里抽要素，绝不替他发散、补全、出主意。
- 抽不准（缺标题、含糊不清）→ confident=false，交给上层反问确认，不瞎猜落库。

复用 reviewer.py 的 JSON 容错解析范式：LLM 只输出一个 JSON 对象。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..llm import LLMClient

_PARSER_SYSTEM = """你是一个"目标解析器"。用户用大白话说了一个想做的事，你把它拆成结构化字段。
你只做翻译，绝不替用户出主意、绝不发散、绝不补他没说的内容。

要抽的字段：
- title：目标标题，简短一句。若用户说的是一个大目标并给了几个步骤/阶段，title 是那个大目标。
- cadence：催收频率，原样保留用户的口语写法（如"每天晚上八点前""每2小时""每30分钟"）。用户没提就留空字符串。
- deadline：单次截止时间，用户明确提到才填（如"这周五前""3月1日"），否则留空字符串。
- subgoals：子目标/步骤列表（字符串数组）。用户明确把大目标拆成了几步/几个阶段才填，每个是一句简短标题；没有拆分就给空数组。
- confident：你是否有把握准确抽出了 title。若用户的话根本没说清要做什么、或含糊到你只能猜，填 false；否则 true。

判断示例：
- "我要每天晚上八点前交健身打卡" → title=健身打卡, cadence=每天晚上八点前, subgoals=[], confident=true
- "重构登录模块，先写接口再接前端最后联调" → title=重构登录模块, subgoals=[写接口,接前端,联调], confident=true
- "我想搞点东西" / "帮我想个目标" → confident=false（没说清做什么，别猜、别帮他想）

你必须只输出一个 JSON 对象，不要任何额外文字：
{"title": "...", "cadence": "...", "deadline": "...", "subgoals": ["...", ...], "confident": true 或 false}"""


@dataclass
class ParsedGoal:
    """解析结果。confident=False 时上层应反问，不落库。"""
    title: str
    cadence: str = ""
    deadline: str = ""
    subgoals: list[str] = field(default_factory=list)
    confident: bool = False


def parse_goal_nl(llm: LLMClient, text: str) -> ParsedGoal:
    """把一句自然语言解析成 ParsedGoal。

    解析失败或 LLM 抽不准 → confident=False，交上层反问，绝不瞎猜落库。
    """
    text = text.strip()
    if not text:
        return ParsedGoal(title="", confident=False)
    try:
        raw = llm.chat(_PARSER_SYSTEM, text)
    except Exception:
        return ParsedGoal(title="", confident=False)
    return _parse(raw)


def _parse(raw: str) -> ParsedGoal:
    """解析 LLM 返回的 JSON。容错：抽不出就 confident=False。"""
    text = raw.strip()
    # 去掉可能的 ```json ``` 包裹
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return ParsedGoal(title="", confident=False)

    title = str(obj.get("title", "")).strip()
    cadence = str(obj.get("cadence", "")).strip()
    deadline = str(obj.get("deadline", "")).strip()
    raw_subs = obj.get("subgoals", [])
    subgoals = [str(s).strip() for s in raw_subs if str(s).strip()] if isinstance(raw_subs, list) else []
    confident = bool(obj.get("confident", False)) and bool(title)
    return ParsedGoal(
        title=title, cadence=cadence, deadline=deadline,
        subgoals=subgoals, confident=confident,
    )
