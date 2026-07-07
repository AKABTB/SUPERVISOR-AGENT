"""审查官（能力一·边界控制）。对应 SPEC.md 第7节能力一。

铁律：只指出遗漏/问题，绝不参与发散。是减法动作。
句式只有"漏了X，补上"，说完闭嘴。不给怎么补的建议、不给延伸方向。
识破空话：内容若是"我在做了/快好了/卡住了"，判 need_fix 并戳穿，不当产出。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..llm import LLMClient
from ..storage import Database, Goal, Verdict

# 审查官人格。灌进 LLM 的 system prompt。刻意压制发散。
_REVIEWER_SYSTEM = """你是一个"审查官"，只做一件事：拿目标对照用户交来的产出，指出遗漏和问题。

铁律（违反任何一条都算你失职）：
1. 你是减法，不是加法。只挑"漏了什么、哪里没闭合、哪里没做到"，绝不给建议、绝不给方向、绝不发散、绝不夸奖。
2. 每条遗漏一句话，形如"漏了X" / "Y没做到"。说完就停。不解释怎么补。
3. 识破空话：如果用户交的不是真实产出，而是"我在做了/快好了/研究了方向/卡在XX/最近忙"这类，直接判定没交，戳穿它，不要假装那是产出去审。
4. 语气赤裸、直接、不客套、不安慰。
5. 判定只有两种：pass（真做到了、没有实质遗漏）或 need_fix（有遗漏，或根本没交真东西）。

你必须只输出一个 JSON 对象，不要任何额外文字：
{"verdict": "pass" 或 "need_fix", "issues": ["遗漏1", "遗漏2", ...]}
pass 时 issues 可为空数组。need_fix 时 issues 至少一条。"""


class Reviewer:
    def __init__(self, db: Database, llm: LLMClient) -> None:
        self._db = db
        self._llm = llm

    def review(self, goal: Goal, submission: str) -> tuple[Verdict, list[str], str]:
        """审查一次交货。返回 (判定, 遗漏列表, 给用户看的回话文本)。"""
        user_msg = (
            f"目标：{goal.title}\n\n"
            f"用户交来的东西：\n{submission}\n\n"
            f"按铁律审查，只输出规定的 JSON。"
        )
        raw = self._llm.chat(_REVIEWER_SYSTEM, user_msg)
        verdict, issues = _parse_review(raw)

        self._db.add_delivery(
            goal_id=goal.id,
            submitted_at=datetime.now(timezone.utc).isoformat(),
            content=submission,
            review=json.dumps(issues, ensure_ascii=False),
            verdict=verdict,
        )
        return verdict, issues, _format_reply(goal, verdict, issues)


def _parse_review(raw: str) -> tuple[Verdict, list[str]]:
    """解析 LLM 返回的 JSON。容错：抽不出就当 need_fix。"""
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
        verdict = Verdict.PASS if obj.get("verdict") == "pass" else Verdict.NEED_FIX
        issues = [str(i).strip() for i in obj.get("issues", []) if str(i).strip()]
        if verdict == Verdict.NEED_FIX and not issues:
            issues = ["没交出真东西。"]
        return verdict, issues
    except (ValueError, json.JSONDecodeError):
        return Verdict.NEED_FIX, ["没看懂你交的是什么——重交，交真东西。"]


def _format_reply(goal: Goal, verdict: Verdict, issues: list[str]) -> str:
    if verdict == Verdict.PASS:
        return f"「{goal.title}」——过了。用 /done {goal.id} 结掉它。下一个。"
    lines = [f"「{goal.title}」——没过。"]
    lines.extend(f"· {it}" for it in issues)
    lines.append("补上再交。")
    return "\n".join(lines)
