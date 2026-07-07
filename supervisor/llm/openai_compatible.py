"""OpenAI 兼容实现。覆盖 OpenAI 官方、DeepSeek 官方、以及各类 OpenAI 兼容网关。

三者都走 openai SDK，仅 base_url / key / model 不同 —— 所以合并成一个实现。
"""
from __future__ import annotations

from openai import OpenAI

from .base import LLMClient


class OpenAICompatibleClient(LLMClient):
    def __init__(self, api_key: str, model: str, temperature: float = 0.3,
                 base_url: str | None = None) -> None:
        if not api_key:
            raise ValueError("缺少 API key —— 请在 .env 中配置对应 provider 的 key。")
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._temperature = temperature

    def chat(self, system_prompt: str, user_message: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
