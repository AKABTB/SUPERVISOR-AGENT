"""步骤4点火：本地直测审查官（不经过TG）。
喂它 (a) 真产出 (b) 空话，看判定对不对、语气硬不硬。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supervisor.config import load_config
from supervisor.core.reviewer import Reviewer
from supervisor.llm import build_llm
from supervisor.storage import Database, Goal, GoalStatus


def main() -> None:
    cfg = load_config()
    db = Database(cfg.db_path)
    reviewer = Reviewer(db, build_llm(cfg.llm))

    goal = Goal(id=1, title="写完登录页的表单校验", is_primary=True,
                status=GoalStatus.ACTIVE, cadence="每天20:00", created_at="")

    print("=== 用例A：真产出（但有明显遗漏，没做错误提示）===")
    sub_a = ("做了登录表单，用户名和密码都加了非空校验，密码长度校验也加了。"
             "提交按钮接了后端接口。")
    v, issues, reply = reviewer.review(goal, sub_a)
    print(f"[判定] {v.value}")
    print(f"[回话]\n{reply}\n")

    print("=== 用例B：空话（没交真东西）===")
    sub_b = "我这两天想了很多，方向挺清楚了，快好了，就是最近有点忙。"
    v, issues, reply = reviewer.review(goal, sub_b)
    print(f"[判定] {v.value}")
    print(f"[回话]\n{reply}\n")

    print("[OK] 步骤4点火完成。")


if __name__ == "__main__":
    main()
