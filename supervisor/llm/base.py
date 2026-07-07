"""LLM 统一接口。对应 SPEC.md 第4节 LLM 适配层。

可切换的落点：核心层只依赖 LLMClient 这个抽象，
换 Claude / OpenAI / DeepSeek / 任何兼容网关，只换实现，核心一行不改。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMClient(ABC):
    @abstractmethod
    def chat(self, system_prompt: str, user_message: str) -> str:
        """一句话进、一句话出。system_prompt 灌人格，user_message 是当前输入。"""
        raise NotImplementedError
