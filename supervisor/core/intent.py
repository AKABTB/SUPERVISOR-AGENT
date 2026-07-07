"""意图识别。区分用户在 Bot 里发的普通消息到底是什么。

只为"拦改"服务：抓出"想改目标定义"的善变意图，硬拦。
其余一律当交货尝试送审查官（审查官自会戳穿借口）。
"""
from __future__ import annotations

from ..llm import LLMClient

_INTENT_SYSTEM = """你是一个意图判别器。用户正在被监督执行一个锁定的目标。
判断用户这句话是不是"想修改/替换/重新定义当前这个目标"（即善变、想中途换需求）。

注意区分：
- "我想把目标改成X" / "其实我真正想做的是Y" / "这个目标不对，应该是Z" → 是想改目标（yes）
- "我做了X" / "我交的是X" / "我卡在X" / "我快好了" / "我在做了" → 不是想改目标，是在交货或找借口（no）

只输出一个词：yes 或 no。不要任何别的字。"""


def is_change_goal_intent(llm: LLMClient, message: str) -> bool:
    """判断这句话是否'想改目标定义'。判不准时保守返回 False（当交货处理）。"""
    try:
        ans = llm.chat(_INTENT_SYSTEM, message).strip().lower()
        return ans.startswith("yes")
    except Exception:
        return False
