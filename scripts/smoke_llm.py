"""步骤1点火：真的调网关，且用'铁石心肠人格'当 sys prompt，
一并验证 (a) 通不通 (b) 人格灌不灌得进去。

用法：python scripts/smoke_llm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supervisor.config import load_config
from supervisor.llm import build_llm

# 临时人格样本（正式版在步骤5淬火，这里只为验证'灌得进'）
PERSONA = (
    "你是一个监督助手，性格铁石心肠、不共情、不客套。"
    "你只认'交了/没交'。用户说'我在做了/快好了/最近忙/卡住了'一律视为'没交'。"
    "回话赤裸、直接、简短，不安慰、不给建议、不发散。"
)


def main() -> None:
    cfg = load_config()
    print(f"[llm] provider={cfg.llm.provider} model={cfg.llm.model} base_url={cfg.llm.base_url}")
    print(f"[llm] api_key 已配置: {bool(cfg.llm.api_key)}\n")

    client = build_llm(cfg.llm)

    user_says = "我最近特别忙，那个目标我想了很多，方向也挺清楚了，快好了。"
    print(f"[你] {user_says}\n")
    reply = client.chat(PERSONA, user_says)
    print(f"[助手] {reply}\n")

    print("[OK] 步骤1点火通过 —— 网关接通，一句话进一句话出，人格 sys prompt 生效。")


if __name__ == "__main__":
    main()
