import os
import anthropic
from src.db import Database

SYSTEM_PROMPT = """你是一个问题澄清专家。帮助用户把模糊的想法变成清晰、可执行的问题定义。

判断标准：
- 低：意图完全模糊
- 中：大方向有了，但缺少关键细节（目标用户、具体场景、成功标准）
- 高：问题清晰，知道是什么、为谁、解决什么

追问策略：每次只问一个最关键的问题，问题要具体。"""

CLARIFY_TOOL = {
    "name": "clarify",
    "description": "评估问题清晰度，若不清晰则追问，若清晰则输出正式定义",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_clear": {
                "type": "boolean",
                "description": "问题是否已经足够清晰"
            },
            "question": {
                "type": "string",
                "description": "若不清晰，向用户提出的下一个问题（只问一个）"
            },
            "definition": {
                "type": "string",
                "description": "若清晰，给出简洁的问题定义（一句话）"
            },
            "clarity_level": {
                "type": "string",
                "enum": ["低", "中", "高"],
                "description": "当前问题的清晰程度"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "关键词标签列表"
            }
        },
        "required": ["is_clear", "clarity_level", "tags"]
    }
}


class ClarificationAgent:
    def __init__(self, api_key: str = None, db_path: str = "orchestrator.db"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.db = Database(db_path)
        self.max_rounds = 5

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
                tools=[CLARIFY_TOOL],
                tool_choice={"type": "tool", "name": "clarify"},
                messages=messages,
            )

            tool_use = next(b for b in response.content if b.type == "tool_use")
            result = tool_use.input

            raw_str = str(result)
            self.db.save_message(session_id, "assistant", raw_str)
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": "ok"}]
            })

            if result.get("is_clear") or round_num == self.max_rounds - 1:
                self.db.save_problem(
                    session_id,
                    result.get("definition") or "（未能完全澄清）",
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

            question = result.get("question", "")
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
