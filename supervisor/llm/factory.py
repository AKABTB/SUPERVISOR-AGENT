"""按配置产出对应的 LLMClient。可切换的开关在这里。"""
from __future__ import annotations

from ..config import LLMConfig
from .base import LLMClient
from .openai_compatible import OpenAICompatibleClient


def build_llm(cfg: LLMConfig) -> LLMClient:
    provider = cfg.provider.lower()

    # deepseek / openai / 兼容网关 都走 OpenAI 兼容接口
    if provider in ("deepseek", "openai"):
        return OpenAICompatibleClient(
            api_key=cfg.api_key or "",
            model=cfg.model,
            temperature=cfg.temperature,
            base_url=cfg.base_url,
        )

    if provider == "claude":
        # Claude 走 anthropic SDK，接口不同 —— 用到时再实现，先明确报错不静默跑偏。
        raise NotImplementedError(
            "claude provider 尚未实现（步骤1只接通了当前所选的 OpenAI 兼容网关）。"
        )

    raise ValueError(f"未知 LLM provider: {cfg.provider}")
