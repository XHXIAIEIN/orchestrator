# Large File Split Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Each task is one file split, fully independent, parallelizable.

**Goal:** Split 10 large files (490-1105 lines) into focused modules while maintaining backward compatibility via re-exports.

**Architecture:** Each large file gets split into 2-6 focused modules. The original file becomes a thin re-export shim so all external imports continue working. No behavior changes — pure structural refactoring.

**Constraint:** Skip `desktop_use/` — another session is working on it.

**Verification:** After each split, run `python -c "from src.<module> import <key_names>"` to confirm imports work.

---

## Universal Pattern

Every split follows this pattern:

1. Read the file, identify logical groups
2. Create new modules with the extracted code
3. Rewrite the original file as a thin re-export shim (`from .new_module import *`)
4. Grep for external imports, verify they still work
5. Run import test

---

## Task 1: Split `src/channels/chat.py` (1105 lines → folder)

**Convert to package `src/channels/chat/`**

**Files:**
- Move: `src/channels/chat.py` → `src/channels/chat/__init__.py` (thin re-exports)
- Create: `src/channels/chat/engine.py` — `do_chat()` main loop + `build_system_prompt()` + `save_to_inbox()`
- Create: `src/channels/chat/db.py` — `db_conn()`, `save_message()`, `load_recent()`, `load_memory()`, `save_memory()`, `count_messages()`, schema migrations
- Create: `src/channels/chat/context.py` — `build_context()`, `_msg_chars()`, `maybe_summarize()`
- Create: `src/channels/chat/tools.py` — `CHAT_TOOLS` schema, `execute_tool()`, all `_tool_*` functions
- Create: `src/channels/chat/router.py` — `_classify_intent()`, `_record_intent()`, `_get_session_momentum()`, signals, `_chat_local*()` functions
- Create: `src/channels/chat/commands.py` — `handle_command()`, all `_cmd_*` functions, `COMMANDS` dict

**Steps:**
- [ ] Create `src/channels/chat/` directory
- [ ] Move `chat.py` content into submodules by logical group
- [ ] Create `__init__.py` that re-exports all public names: `do_chat`, `handle_command`, `build_system_prompt`, `save_message`, `load_recent`, `CHAT_TOOLS`, `execute_tool`, `save_to_inbox`, `build_context`
- [ ] Fix internal cross-references between submodules
- [ ] Verify: `python -c "from src.channels.chat import do_chat, handle_command, build_system_prompt, CHAT_TOOLS"`

---

## Task 2: Split `src/storage/events_db.py` (963 lines → mixin pattern)

**Use mixin classes to decompose the monolith EventsDB**

**Files:**
- Keep: `src/storage/events_db.py` — `EventsDB` class (inherits mixins), `__init__`, `_connect`, `_connect_safe`, `_init_tables`, `get_tables`, `get_size_bytes`
- Create: `src/storage/_schema.py` — table DDL strings + migration logic (extracted from `_init_tables`)
- Create: `src/storage/_tasks_mixin.py` — `TasksMixin`: `create_task`, `update_task`, `get_tasks`, `get_task`, `get_running_task`, `get_running_tasks`, `count_running_tasks`
- Create: `src/storage/_profile_mixin.py` — `ProfileMixin`: `save_daily_summary`, `get_daily_summaries`, `save_user_profile`, `get_latest_profile`, `save_insights`, `get_latest_insights`, `save_profile_analysis`, `get_profile_analysis`, `insert_event`, `get_recent_events`, `get_events_by_day`, `get_events_by_category`
- Create: `src/storage/_learnings_mixin.py` — `LearningsMixin`: `add_learning`, `promote_learning`, `retire_learning`, `get_learnings`, `get_promoted_learnings`, `get_learnings_for_dispatch`
- Create: `src/storage/_runs_mixin.py` — `RunsMixin`: `write_log`, `get_logs`, `set_scheduler_status`, `get_scheduler_status`, `append_run_log`, `get_recent_run_logs`, `get_all_run_logs`, `get_department_run_stats`, `create_sub_run`, `finish_sub_run`, `get_sub_runs`, `add_experience`, `get_recent_experiences`, `get_experiences_by_type`, `count_experiences`, `add_agent_event`, `get_agent_events`, `get_live_agent_events`, `get_last_run_hash`, `save_session`, `get_session`, `record_heartbeat`, `get_last_heartbeat`, `upsert_file_index`, `query_file_index`

**Steps:**
- [ ] Extract DDL strings and migration SQL into `_schema.py` as constants
- [ ] Create mixin classes, each with methods that call `self._connect()`
- [ ] Rewrite `EventsDB` as: `class EventsDB(TasksMixin, ProfileMixin, LearningsMixin, RunsMixin):`
- [ ] Verify: `python -c "from src.storage.events_db import EventsDB; db = EventsDB(':memory:'); print(db.get_tables())"`

---

## Task 3: Split `src/channels/telegram/channel.py` (791 lines)

**Files:**
- Keep: `src/channels/telegram/channel.py` — `TelegramChannel` class (init, start, stop, polling, `_handle_update`, `_start_chat`, `_get_system_prompt`, `_scan_project_tree`)
- Create: `src/channels/telegram/sender.py` — `TelegramSender` mixin: `send`, `_send_approval_with_buttons`, `_send_text`, `_split_message`, `_send_raw`, `_set_reaction`, `_send_photo*`, `_send_document`, `_send_voice`, `_send_video`, `_send_sticker`, `_send_multipart`, `_reply_media`
- Create: `src/channels/telegram/handler.py` — `TelegramHandler` mixin: `_flush_pending`, `_process_message`, `_handle_reaction`, `_handle_callback_query`, `_download_tg_file`, `_describe_media`, `_transcribe`, `_keep_typing`, `_send_typing`
- Create: `src/channels/telegram/api.py` — `TelegramAPI` mixin: `_tg_api`, `_tg_get_file_url`

**Steps:**
- [ ] Create mixin classes in new files
- [ ] Rewrite `TelegramChannel` as: `class TelegramChannel(TelegramSender, TelegramHandler, TelegramAPI, Channel):`
- [ ] Verify: `python -c "from src.channels.telegram.channel import TelegramChannel"`

---

## Task 4: Split `src/governance/policy/policy_advisor.py` (613 lines)

**Files:**
- Keep: `src/governance/policy/policy_advisor.py` — `PolicyAdvisor` class (core + auto_apply + blueprint I/O)
- Create: `src/governance/policy/observer.py` — `record_denial()`, `observe_task_execution()`, `_detect_tool_friction()`, `load_denials()`, `aggregate_denials()`
- Create: `src/governance/policy/suggester.py` — `generate_suggestions()`, `generate_all_suggestions()`

**Steps:**
- [ ] Extract module-level functions into observer.py and suggester.py
- [ ] Update imports in policy_advisor.py to use the new modules
- [ ] Add re-exports to maintain backward compat
- [ ] Verify: `python -c "from src.governance.policy.policy_advisor import PolicyAdvisor"`

---

## Task 5: Split `src/governance/executor.py` (560 lines)

**Files:**
- Keep: `src/governance/executor.py` — `TaskExecutor` class (execute_task, execute_task_async)
- Create: `src/governance/executor_prompt.py` — `PromptBuilder` class: prompt assembly logic (authority ceiling, cognitive mode, context injection)
- Create: `src/governance/executor_session.py` — `AgentSessionRunner` class: `_run_agent_session`, stuck detection, doom loop logic

**Steps:**
- [ ] Extract `_prepare_prompt` logic into `PromptBuilder`
- [ ] Extract `_run_agent_session` into `AgentSessionRunner`
- [ ] TaskExecutor composes both: `self._prompt_builder = PromptBuilder()`, `self._session_runner = AgentSessionRunner()`
- [ ] Verify: `python -c "from src.governance.executor import TaskExecutor"`

---

## Task 6: Split `src/channels/wechat/channel.py` (557 lines)

**Files:**
- Keep: `src/channels/wechat/channel.py` — `WeChatChannel` class (init, start, stop, polling)
- Create: `src/channels/wechat/sender.py` — `WeChatSender` mixin: `send`, `_reply_text`, `_reply_media`
- Create: `src/channels/wechat/handler.py` — `WeChatHandler` mixin: `_handle_message`, `_flush_pending`, `_process_message`, `_download_media_item`, `_describe_media`, `_start_chat`, `_keep_typing`, `_fetch_typing_ticket`, `_send_typing_indicator`
- Create: `src/channels/wechat/utils.py` — `_silk_to_wav`, `_split_message`, `_strip_markdown`

**Steps:**
- [ ] Create mixin classes + utils
- [ ] Rewrite `WeChatChannel` to inherit mixins
- [ ] Verify: `python -c "from src.channels.wechat.channel import WeChatChannel"`

---

## Task 7: Split `src/governance/review.py` (518 lines)

**Files:**
- Keep: `src/governance/review.py` — `ReviewManager` class (init, finalize_task, _visual_verify)
- Create: `src/governance/review_dispatch.py` — `ReviewDispatcher`: `_dispatch_quality_review`, `_dispatch_rework` logic

**Steps:**
- [ ] Extract dispatch methods into `ReviewDispatcher` class
- [ ] ReviewManager composes or inherits ReviewDispatcher
- [ ] Verify: `python -c "from src.governance.review import ReviewManager"`

---

## Task 8: Split `src/core/llm_router.py` (511 lines)

**Files:**
- Keep: `src/core/llm_router.py` — `LLMRouter` class (generate, generate_rich, check_ollama), singleton
- Create: `src/core/llm_models.py` — All constants: `MODEL_*`, `ROUTES`, `MODEL_TIERS`, `DEPTH_TIERS`, `THRESHOLD_MODES`, `GenerateResult`, `get_min_response_len()`
- Create: `src/core/llm_backends.py` — Backend implementations: `OllamaBackend`, `ClaudeBackend`, `ChromeAIBackend` classes (extracted from `_ollama_generate`, `_claude_generate`, `_chrome_ai_generate` etc.)

**Steps:**
- [ ] Move constants + GenerateResult to llm_models.py
- [ ] Extract backend methods into backend classes
- [ ] LLMRouter composes backends
- [ ] Re-export key names from llm_router.py for backward compat
- [ ] Verify: `python -c "from src.core.llm_router import LLMRouter, get_router, MODEL_SONNET, MODEL_HAIKU, GenerateResult, DEPTH_TIERS"`

---

## Task 9: Split `src/core/browser_tools.py` (508 lines)

**Files:**
- Keep: `src/core/browser_tools.py` — re-exports all tool functions
- Create: `src/core/browser_navigation.py` — `browser_navigate`, `browser_read_page`, `browser_search`, `browser_snapshot`, `_SNAPSHOT_JS`
- Create: `src/core/browser_interaction.py` — `browser_click_index`, `browser_click`, `browser_click_at`, `browser_fill`, `browser_scroll`, `browser_send_keys`, `browser_find_text`, `browser_evaluate`

**Steps:**
- [ ] Split functions by navigation vs interaction
- [ ] browser_tools.py becomes `from .browser_navigation import *; from .browser_interaction import *`
- [ ] Verify: `python -c "from src.core.browser_tools import browser_navigate, browser_click, browser_fill"`

---

## Task 10: Split `src/core/browser_runtime.py` (491 lines)

**Files:**
- Keep: `src/core/browser_runtime.py` — `BrowserRuntime` class (main orchestrator, lifecycle, health)
- Create: `src/core/browser_cdp.py` — `CDPClient` class + `TabLease` dataclass

**Steps:**
- [ ] Move CDPClient and TabLease to browser_cdp.py
- [ ] Import in browser_runtime.py
- [ ] Verify: `python -c "from src.core.browser_runtime import BrowserRuntime"`
</content>
</invoke>