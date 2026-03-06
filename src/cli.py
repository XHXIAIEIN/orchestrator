import sys
from pathlib import Path
from src.config import load_api_key, save_api_key
from src.agent import ClarificationAgent
from src.db import Database

DB_PATH = str(Path(__file__).parent.parent / "orchestrator.db")


def ensure_api_key() -> str:
    key = load_api_key()
    if key:
        return key

    # 最后手段：让用户粘贴一次
    print("未找到 ANTHROPIC_API_KEY。")
    print("请前往 https://console.anthropic.com 获取，然后粘贴到这里：")
    key = input("API Key: ").strip()
    if key:
        save_api_key(key)
        print("已保存到 .env，下次自动加载。\n")
    return key


def run():
    key = ensure_api_key()
    if not key:
        print("没有 API key，无法启动。")
        sys.exit(1)

    agent = ClarificationAgent(api_key=key, db_path=DB_PATH)

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
