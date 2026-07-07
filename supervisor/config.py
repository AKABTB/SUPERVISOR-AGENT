"""配置加载：config.yaml（可读配置）+ .env（密钥）。对应 SPEC.md 第5节。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LLMConfig:
    provider: str
    model: str
    temperature: float
    api_key: str | None
    base_url: str | None = None


@dataclass
class Config:
    llm: LLMConfig
    db_path: str
    timezone: str
    telegram_token: str | None
    telegram_owner_chat_id: str | None
    telegram_proxy: str | None
    web_host: str
    web_port: int


_ENV_KEY_BY_PROVIDER = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def load_config(config_path: str | None = None) -> Config:
    load_dotenv(_ROOT / ".env")

    path = Path(config_path) if config_path else _ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    llm_raw = raw.get("llm", {})
    provider = llm_raw.get("provider", "deepseek")
    api_key = os.getenv(_ENV_KEY_BY_PROVIDER.get(provider, ""), None)

    return Config(
        llm=LLMConfig(
            provider=provider,
            model=llm_raw.get("model", ""),
            temperature=float(llm_raw.get("temperature", 0.3)),
            api_key=api_key,
            base_url=llm_raw.get("base_url") or None,
        ),
        db_path=str(_ROOT / raw.get("storage", {}).get("db_path", "data.db")),
        timezone=raw.get("supervisor", {}).get("timezone", "Asia/Shanghai"),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_owner_chat_id=os.getenv("TELEGRAM_OWNER_CHAT_ID"),
        telegram_proxy=raw.get("telegram", {}).get("proxy") or None,
        web_host=raw.get("web", {}).get("host", "127.0.0.1"),
        web_port=int(raw.get("web", {}).get("port", 8000)),
    )
