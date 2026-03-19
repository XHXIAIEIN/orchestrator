import json
import anthropic
from src.core.config import get_anthropic_client
from src.core.db import Database
from src.core.tools import SYSTEM_TOOLS, TOOL_HANDLERS, CLARIFY_TOOL  # noqa: F401

SYSTEM_PROMPT = """你是一个问题澄清专家。帮助用户把模糊的想法变成清晰、可执行的问题定义。

你有系统探测工具可以主动调用，用来获取操作系统、浏览器、Git 仓库、Steam、Claude 会话等信息。
能用工具查到的信息，绝对不要问用户。只有工具查不到的主观意图才需要问用户。

判断标准：
- 低：意图完全模糊
- 中：大方向有了，但缺少关键细节
- 高：问题清晰，知道是什么、为谁、解决什么

追问策略：每次只问一个最关键的、工具无法回答的主观问题。"""

ALL_TOOLS = SYSTEM_TOOLS + [CLARIFY_TOOL]


class ClarificationAgent:
    def __init__(self, db_path: str = "orchestrator.db"):
        self.client = get_anthropic_client()
        self.db = Database(db_path)
        self.max_rounds = 5

    def run(self, initial_input: str, user_replies: list = None) -> dict:
        session_id = self.db.create_session(initial_input)
        messages = [{"role": "user", "content": initial_input}]
        self.db.save_message(session_id, "user", initial_input)

        reply_queue = list(user_replies) if user_replies else []
        clarify_round = 0

        for _ in range(30):  # 最多 30 次 API 调用（含系统工具）
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=ALL_TOOLS,
                messages=messages,
            )

            # 分类 tool_use blocks
            system_blocks = [b for b in response.content if b.type == "tool_use" and b.name != "clarify"]
            clarify_block = next((b for b in response.content if b.type == "tool_use" and b.name == "clarify"), None)

            # 处理系统工具调用（无 clarify）
            if system_blocks and not clarify_block:
                tool_results = []
                for block in system_blocks:
                    handler = TOOL_HANDLERS.get(block.name)
                    data = handler() if handler else {"error": f"unknown tool: {block.name}"}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(data, ensure_ascii=False, default=str),
                    })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                continue

            # 处理 clarify（可能同时有系统工具结果）
            if clarify_block:
                result = clarify_block.input
                self.db.save_message(session_id, "assistant", str(result))
                clarify_round += 1

                if result.get("is_clear") or clarify_round >= self.max_rounds:
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
                        "rounds": clarify_round,
                    }

                # 需要用户回答：把 tool_result + 用户回复合并进同一条 user message
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

                # assistant message + user message（tool_result + 用户文字合并）
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": clarify_block.id, "content": "ok"},
                        {"type": "text", "text": user_reply},
                    ],
                })
                continue

            # stop_reason = end_turn，没有 tool_use
            break

        return {"session_id": session_id, "definition": None, "clarity_level": "低", "tags": [], "rounds": clarify_round}
