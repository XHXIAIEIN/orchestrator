import json
import os
import anthropic
from src.db import Database

SYSTEM_PROMPT = """你是一个问题澄清专家。你的唯一工作是帮助用户把模糊的想法变成清晰、可执行的问题定义。

每次回复必须是严格的 JSON 格式，不能有任何其他文字：

{
  "is_clear": true/false,
  "question": "如果不清晰，问用户的下一个问题（只问一个）",
  "definition": "如果清晰了，给出简洁的问题定义（一句话）",
  "clarity_level": "低/中/高",
  "tags": ["关键词1", "关键词2"]
}

判断标准：
- 低：意图完全模糊，不知道要做什么
- 中：大方向有了，但缺少关键细节（目标用户、具体场景、成功标准）
- 高：问题清晰，知道是什么、为谁、解决什么

追问策略：
- 每次只问一个最关键的问题
- 最多追问 5 次，超过则强制输出当前最佳理解
- 问题要具体，不要泛泛而谈"""


class ClarificationAgent:
    def __init__(self, api_key: str = None, db_path: str = "orchestrator.db"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.db = Database(db_path)
        self.max_rounds = 5

    def _parse_response(self, content: str) -> dict:
        content = content.strip()
        # 去掉 markdown 代码块包裹
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]).strip()
        # 提取第一个完整 JSON 对象
        start = content.find("{")
        end = content.rfind("}") + 1
        if start != -1 and end > start:
            content = content[start:end]
        return json.loads(content)

    def run(self, initial_input: str, user_replies: list = None) -> dict:
        session_id = self.db.create_session(initial_input)
        messages = [{"role": "user", "content": initial_input}]
        self.db.save_message(session_id, "user", initial_input)

        reply_queue = list(user_replies) if user_replies else []

        for round_num in range(self.max_rounds):
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=messages,
            )

            raw = response.content[0].text
            result = self._parse_response(raw)
            self.db.save_message(session_id, "assistant", raw)
            messages.append({"role": "assistant", "content": raw})

            if result.get("is_clear") or round_num == self.max_rounds - 1:
                self.db.save_problem(
                    session_id,
                    result.get("definition", "（未能完全澄清）"),
                    result.get("clarity_level", "低"),
                    result.get("tags", []),
                )
                return {
                    "session_id": session_id,
                    "definition": result.get("definition"),
                    "clarity_level": result.get("clarity_level"),
                    "tags": result.get("tags", []),
                    "rounds": round_num + 1,
                }

            question = result["question"]
            if reply_queue:
                user_reply = reply_queue.pop(0)
            else:
                print(f"\nAgent: {question}")
                try:
                    user_reply = input("用户: ").strip()
                except EOFError:
                    break

            self.db.save_message(session_id, "user", user_reply)
            messages.append({"role": "user", "content": user_reply})

        return {"session_id": session_id, "definition": None, "rounds": self.max_rounds}
