import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from src.agent import ClarificationAgent
from src.db import Database

load_dotenv()

DB_PATH = str(Path(__file__).parent.parent / "orchestrator.db")


def run():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("错误：请设置 ANTHROPIC_API_KEY 环境变量")
        print("复制 .env.example 为 .env 并填入你的 key")
        sys.exit(1)

    agent = ClarificationAgent(api_key=api_key, db_path=DB_PATH)

    print("=== Orchestrator v0 ===")
    print("输入你的想法或问题（Ctrl+C 退出）\n")

    try:
        while True:
            initial_input = input("你: ").strip()
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
