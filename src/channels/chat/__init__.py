"""Chat engine — split into submodules for maintainability."""
from src.channels.chat.engine import do_chat, build_system_prompt, save_to_inbox
from src.channels.chat.db import save_message, load_recent, load_memory, save_memory, count_messages
from src.channels.chat.context import build_context, maybe_summarize
from src.channels.chat.tools import CHAT_TOOLS, execute_tool
from src.channels.chat.router import (
    _classify_intent, _chat_local, _chat_local_reason, _chat_local_vision,
)
from src.channels.chat.commands import handle_command, COMMANDS
