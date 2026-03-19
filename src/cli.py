import sys
from pathlib import Path
from src.core.agent import ClarificationAgent
from src.core.db import Database

DB_PATH = str(Path(__file__).parent.parent / "orchestrator.db")


def run():
    try:
        agent = ClarificationAgent(db_path=DB_PATH)
    except RuntimeError as e:
        print(f"认证失败：{e}")
        sys.exit(1)

    print("=== Orchestrator v0 ===")
    print("输入你的想法或问题（Ctrl+C 退出）\n")

    try:
        while True:
            initial_input = input("用户: ").strip()
            if not initial_input:
                continue

            print("\n[开始澄清...]\n")
            result = agent.run(initial_input)

            print("\n" + "=" * 40)
            print(f"问题定义: {result['definition']}")
            print(f"清晰度:   {result['clarity_level']}")
            print(f"标签:     {', '.join(result['tags'])}")
            print(f"用时轮数: {result['rounds']}")
            print(f"会话 ID:  {result['session_id']}")
            print("=" * 40 + "\n")

    except KeyboardInterrupt:
        print("\n\n已退出。")
        db = Database(DB_PATH)
        problems = db.get_problems()
        if problems:
            print(f"\n共定义了 {len(problems)} 个问题，已存入数据库。")


def main():
    run()


if __name__ == "__main__":
    main()
