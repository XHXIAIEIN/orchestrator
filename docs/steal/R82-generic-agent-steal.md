# R82 — GenericAgent Steal Report

**Source**: https://github.com/lsdefine/GenericAgent | **Stars**: (Trendshift featured, 2025) | **License**: MIT
**Date**: 2026-04-18 | **Category**: Self-Evolving

## TL;DR

一个 ~3K 行的自演化 Agent 框架，其真正价值不是 "9 原子工具+百行 loop" 的口号，而是**把对 LLM 的物理级约束做到了引擎层**——turn 粒度的节奏惩罚、`no_tool` 虚拟工具拦截"假声称完成"、out-of-band 文件干预通道、plan 模式下强制对抗性 VERIFY subagent。这些是 prompt 写不出来、只能在 runtime 里实现的硬约束。

## Architecture Overview

四层结构（从物理到逻辑）：

```
Layer 0 (Engine):    agent_loop.py (122 LOC)
                     - StepOutcome DSL (should_exit / next_prompt)
                     - 每轮 messages=[new only]（历史在 backend.history）
                     - 每 10 轮 last_tools='' 强制重投 schema
                     - generator-based yield pipeline（verbose 流式）

Layer 1 (Handler):   ga.py::GenericAgentHandler
                     - 9 个 do_<tool> 方法 + no_tool 虚拟拦截
                     - turn_end_callback: 7/10/35 节奏规则 + _keyinfo/_intervene 读取
                     - working[key_info/related_sop/in_plan_mode]
                     - _get_anchor_prompt: 滚动 history(20条summary) + turn + key_info

Layer 2 (Memory):    L0 sys_prompt + L1 insight(≤30行) + L2 facts(可膨胀)
                     + L3 ../memory/{*.md,*.py} SOP+脚本混居
                     + L4 zipped monthly archive with sliding-window history merge

Layer 3 (Trigger):   CLI (stdin) / file IO (--task name) / reflect (--reflect script)
                     / bot 前端 (feishu/wechat/tg/qq/dingtalk/wecom)
                     + scheduler.py port-lock cron
```

关键 "loop 即 DSL" 设计：`StepOutcome.next_prompt` 为空 → 任务完成；`should_exit=True` → 强制退出；两者都不给 → 继续循环。单一返回值推动整条状态机。

## Six-Dimensional Scan

| 维度 | 观察到什么 |
|------|-----------|
| **Security / Governance** | 物理级：`file_patch` 唯一匹配强制（count==0/>1 都拒绝并给具体建议，明令"严禁 overwrite 替代"）；`plan_mode` 下完成声明必须带 `VERDICT`/`[VERIFY]` 关键词否则拦截；ask_user 是显式工具，主 agent 在 plan 模式下被禁止自己做环境探测（必须委托 subagent）。prompt 级规则在 sys_prompt.txt 里只有 **7 行**——绝大多数约束是引擎挡住的。 |
| **Memory / Learning** | 4 层 + 4 公理（Action-Verified / Sanctity / No Volatile / Minimum Pointer）；L1≤30 行硬约束；L4 session 压缩带**滑动窗口 history merge**（用 LCS-style suffix-prefix 把 20 条滚动窗口拼成完整序列）；file_read 路径含 `memory/sop` 时自动注入"提取到 working memory"提示（被动晋升）。file_access_stats.json 记录访问频次（回馈 L1 精简决策）。 |
| **Execution / Orchestration** | Handler 用 **generator yield** 流式输出，支持 verbose/non-verbose 双模式；每轮 `messages = [{new}]` 丢弃完整对话（历史存在 llmclient.backend），只带 anchor prompt（last 20 summaries + key_info）。plan 模式把 max_turns 从 40 提到 80，且每 5 轮强制 file_read plan.md 引用当前步骤。 |
| **Context / Budget** | compress_history_tags 每 5 次调用触发一次：`<thinking>/<tool_use>/<tool_result>` 头尾截断（max_len=800），`<history>/<key_info>` 直接塌缩成 `<history>[...]</history>`。trim_messages_history 在 cost>context_win*3 时弹掉最老消息，并 sanitize 首条 user（把孤立的 tool_result 块转成纯文本）。每 10 轮强制重发 tools schema（`client.last_tools=''`）——作者称是对抗 context rot。 |
| **Failure / Recovery** | 7/10/35 turn-based cadence（见 P0-1）；generator 异常直接冒泡；`code_run` 支持 stop_signal 列表、超时强杀；`_stop` 文件可在任何轮次结束时触发退出。`do_no_tool` 检测"未收到完整响应"/"max_tokens"/"空响应"并给不同的下轮 prompt。 |
| **Quality / Review** | plan 模式强制 `[VERIFY]` 步骤由**独立 subagent** 执行（verify_sop.md 开篇就写"你的两个失败模式：验证回避、被前80%迷惑"）；按交付物类型分 checklist（网页/脚本/数据/API/配置/bug/批量）；对抗性探测必须至少一项（边界值/幂等性/缺失依赖/孤儿ID）。VERDICT 字面量 `PASS/FAIL/PARTIAL` 无变体。 |

## Depth Layers

| 层 | 追踪发现 |
|----|----------|
| **调度层** | `agent_runner_loop` 是单协程 yield；并发在 handler 里：subagent 通过 `subprocess.Popen(--bg)` 拉起独立进程，父子通过 `temp/{task}/{input,output,reply,_stop,_keyinfo,_intervene}.txt` 文件通信。Map 模式 = N 个 subagent 并行，共享文件系统但键鼠/浏览器互斥。scheduler.py 是独立 `reflect` 进程，check() 每 INTERVAL 秒返回 task string 就触发。 |
| **实践层** | `_get_anchor_prompt` 是核心：滚动 20 条 summary（不是完整 history）+ current_turn + key_info + related_sop → 塞进下轮 prompt。summary 提取自 `<summary>` 标签，缺失则用 tool_name+args 兜底并注入 `[DANGER] 上轮遗漏 <summary>`。compress_session 的 sliding-window merge (`_merge_history_blocks`) 用后缀-前缀 LCS 对齐多份重叠窗口，是 L4 能重建完整历史的关键。 |
| **消费层** | 输出经过 `_clean_content`：shrink 长代码块到前5行+"(N lines)"；strip `<file_content>/<tool_use>` 标签；折叠三连换行。`display_queue` 支持 incremental 输出（inc_out=True 每次只发增量）。下游 bot 前端（fsapp.py/wechatapp.py）各自格式化——feishu 还支持 vision 首轮多模态直传。 |
| **状态层** | 没有数据库。所有状态在文件系统：`memory/*` 是记忆，`temp/{task}/*` 是任务 I/O，`temp/model_responses/*.txt` 是原始会话日志，12h cron 压缩归档成 `L4_raw_sessions/MMDD_HHMM-MMDD_HHMM.txt` + 月度 zip。`file_access_stats.json` 记录记忆文件访问热度（用于 GC 决策）。 |
| **边界层** | `file_patch` 的 count 检查是"严禁自行使用 overwrite"的物理防线；`expand_file_refs` 的 `{{file:x:N:M}}` 引用展开失败直接 raise ValueError（不容忍静默失败）；`file_read` FileNotFound 时用 difflib 给 top-5 fuzzy match（防止模型猜路径）；slash `/session.KEY=VALUE` 能 setattr 任意后端属性（开口极大，但显式 raw_query 注释说"知道危险，反正 raw_query 本身就危险"）。 |

## Path Dependency (Speed-Assess)

- **Locking decisions**: 早期选"不依赖任何框架 + 直接裸 HTTP SSE 解析"把项目锁进了"3K 行极简"品牌，代价是每新增一个 LLM provider 都要手写 SSE parser（Anthropic/OpenAI/Responses API 各一套）。选"文件系统作状态层"锁进了"单机/低并发"场景，但也让整个系统对 ops 极友好（看 `memory/` 目录就能理解 Agent 状态）。
- **Missed forks**: 可以走"LangGraph/DSPy 节点图"路线但没走——这保留了 Handler 的直白可读性，代价是 Handler 里手动维护的状态机（in_plan_mode / code_stop_signal / working）如果再扩容会崩。可以把 L4 做成 SQLite 但选了 zip——读取需要先解压（查询只能做文件名范围筛选），但杜绝了 schema 迁移。
- **Self-reinforcement**: "skill 都是 .md + .py 混居在 memory/" 这个决定让生态围绕文件操作而非 ORM 生长——新功能 = 新 SOP 文件 + 可选工具脚本，零门槛。105K skill 库用 semantic search API 外挂，反向强化了"我们核心是 3K 行，skill 是外挂"的品牌。
- **Lesson for us**: **学它的 runtime 物理约束，不学它的裸奔架构**。我们有 docker/db/worktree，学 GenericAgent 不意味着放弃这些——意味着把 "物理级拦截" 的思想搬到我们的 hook/skill-constraint 层。

## Steal Sheet

### P0 — Must Steal (5 patterns)

| Pattern | Mechanism | Our Current State | Adaptation | Effort |
|---------|-----------|------------------|------------|--------|
| **Turn-cadence governance (7/10/35)** | `turn_end_callback` 按 turn % 7/10/35 注入不同严重度的 [DANGER] 提示：7=禁止无效重试+强制策略切换；10=重注 global memory；35=强制 ask_user（plan 模式额外 70=汇报确认）。 | **完全空缺**。我们只有 max_turns 上限 + prompt 级 "diagnose root cause" 劝告，没有按轮数自动升级的物理约束。agent 连续重试 20 次既不会被打断也不会被强制重注记忆。 | 在 `.claude/skills/` 下建 `turn-cadence/` skill 或直接改 orchestrator/engineer agent 的 turn-end hook。阈值直接搬：7/10/35，plan/debug 任务额外加 70。 | ~3h |
| **`no_tool` virtual interception** | LLM 回复无 tool call 时，引擎**合成**一个 `no_tool` 调用并路由到 `do_no_tool`。该 handler 检测：①"包含大代码块但无 tool call 且后面几乎无自然语言" → 拦截并要求补工具或解释；②plan 模式下出现"任务完成"但无 `[VERIFY]/VERDICT` 关键词 → 拦截拒绝；③max_tokens 截断/空响应 → 要求重生成。 | **部分覆盖**。我们的 verification-gate skill 是 prompt 级（告诉 agent "禁止使用 should pass 等词"），但没有引擎级拦截——agent 可以贴一段代码就说"完成"而不会被打断。 | 把 no_tool 拦截思想落到 **SessionStart 或 UserPromptSubmit hook** 或更好——加到 `.claude/hooks/` 的 PostToolUse/Stop hook：当 Stop 触发且响应含"完成/complete"但缺 [VERIFY] token 时，写 exit_code≠0 的 block 消息（Claude Code hook 协议）把 agent 打回继续。 | ~4h |
| **Out-of-band master intervention (`_stop/_keyinfo/_intervene`)** | 父 agent 写 `temp/{task}/_stop` / `_keyinfo` / `_intervene` 文件；子 agent 的 `turn_end_callback` 每轮结束 `consume_file`（读+删），把内容注入下一轮 prompt 或 working memory。**物理 channel，不经 LLM**。 | **完全空缺**。我们用 Agent 工具派发 subagent 后只能等 return，无法中途纠偏或注入补充信息。长任务跑偏只能 esc esc 从头再来。 | 在 Agent 工具派发时传 `temp_dir` 给子代理，约定 `_intervene.txt`/`_keyinfo.txt`/`_stop.txt`。主 agent 通过 Monitor 工具 tail subagent output.txt，发现跑偏时写 `_intervene`。子代理 turn-end hook（Claude Code 的 StopHook）读这三个文件。 | ~6h |
| **Plan mode + adversarial VERIFY subagent + plan.md `[ ]` 自动退出** | 进入 plan 模式时 `handler.working['in_plan_mode'] = plan_path` + `max_turns *= 2`；每轮 turn_end_callback 检查 plan.md 中 `[ ]` 数量，=0 时自动退出 plan 模式；完成前强制启动独立 subagent 按 verify_sop.md（65 行对抗性脚本：两个失败模式 + 按产物类型的 checklist + 必须至少一项对抗探测）给 VERDICT：PASS/FAIL/PARTIAL。 | **部分覆盖**。我们有 `plan_template.md` + `verification-gate/SKILL.md`，但验证是主 agent 自己跑的（有 confirmation bias），没有独立 subagent 对抗验证。plan 完成检测靠 TodoWrite 状态，不强制 file_read 核对。 | ①把 verify_sop.md 的"两个失败模式"+"识别合理化借口"列表 fork 进我们 `.claude/skills/verification-gate/`；②新增 `.claude/skills/verify-subagent/` 规定主 agent 完成 plan 后**必须**通过 Agent(subagent_type=verifier) 派发独立验证，读 VERDICT 字面量；③plan_sop.md 的 `[VERIFY]` 作为 plan_template 的强制最后一步。 | ~5h |
| **4 记忆公理 + file_access_stats 热度回馈** | L0: Action-Verified Only（"No Execution, No Memory"）/ Sanctity of Verified Data（GC 时不得丢失）/ No Volatile State（禁 PID/时间戳/session ID）/ Minimum Sufficient Pointer。`log_memory_access` 在每次 file_read 记忆文件时给 `file_access_stats.json` 累加计数+时间戳，供下次 GC 决定哪些 L3 能晋升到 L1。 | **部分覆盖**。我们有 R42 evidence tiers（verbatim/artifact/impression），但没有 Action-Verified 硬性要求、没有 Sanctity 保护、没有访问热度统计。内存晋升完全靠手动 classify。 | ①在 `SOUL/public/prompts/` 下加 `memory_axioms.md`，4 公理作为写记忆前的 gate；②evidence 字段扩展 `action_verified: bool`（指向具体 commit/run 证据）；③memory 读操作走统一 wrapper 累加 `file_access_stats.json`；月末 cron 把高频 L3 晋升 L1 候选。 | ~4h |

### P1 — Worth Doing (7 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **`{{file:path:start:end}}` paste-by-reference** | `expand_file_refs` 在 file_write/file_patch 展开 `{{file:x.py:10:50}}` 为实际文件行。失败直接 ValueError（不容忍静默）。避免 LLM 在 output 里 echo 大段内容。 | Claude Code 的 Edit 工具没有这个；可在 `.claude/skills/paste-ref/` 或工具包装层实现——当 new_string 含 `{{file:...}}` 模式时先展开。 | ~2h |
| **file_patch 唯一匹配 + 反 workaround 提示** | count==0: "先用 file_read 确认当前内容，再分小段 patch"；count>1: "提供更长更具体旧文本块确保唯一性，包含上下文行"；**明令**"严禁自行使用 overwrite 或代码替换"。 | Claude Code Edit 已经强制唯一匹配，但错误消息没有"禁止 workaround"的反劝告。在 AGENTS.md 或 edit-integrity skill 里加一句"Edit 失败 3 次 → ask_user，禁止改用 Write 覆盖"。 | ~1h |
| **file_read fuzzy-match "Did you mean"** | FileNotFound 时扫描已 read 过的目录，用 `difflib.SequenceMatcher` 计算 basename 相似度，返回 top-5 > 30% 的候选+百分比。 | 包装 Read 工具：拦截 FileNotFound，scan `.claude/`/`SOUL/`/当前目录 bi- depth 2，给 fuzzy 建议。 | ~2h |
| **Scheduler port-lock singleton + max_delay_hours** | `_lock = socket.bind(('127.0.0.1', 45762))` 防重复启动；`try _lock except NameError` 让 mtime 热重载不解锁。`max_delay_hours` (默认6h) 防"下午开机触发凌晨任务"雪崩。 | 我们的 cron 系统（CronCreate 工具）是否有类似防护？若无，包装层加 port lock；CronCreate 加 `max_delay_hours` 参数。 | ~3h |
| **Memory-read auto hint** | file_read 路径含 `memory/sop` 时，自动在 next_prompt 尾部追加"读到记忆/SOP 文件时请提取关键点更新 working memory"。被动晋升机制。 | 在 Read tool hook 或 skill-loading 路径上加：读取 `.claude/skills/*/SKILL.md` 时自动在 response 里提示"如决定按此 skill 执行，先 TodoWrite 立项"。 | ~2h |
| **compress_history_tags periodic + sliding-window merge** | 每 5 次 chat 调用 shrink 老消息里的 `<thinking>/<tool_use>/<tool_result>`（头尾各 400 字符）；`<history>/<key_info>` 直接塌缩为 `<tag>[...]</tag>`。L4 压缩时用 LCS suffix-prefix merge 拼回完整 history（因为每轮只存 20 条滚动窗口）。 | ①我们当前是整包 compact，没有 tag 粒度选择性压缩——对 Opus 长上下文场景值得借鉴；②滑动窗口 merge 算法直接 fork 进 `compiler/` 或归档脚本，可用于合并多个 partial session log。 | ~4h |
| **subagent 文件 IO 协议 + `[ROUND END]` sentinel** | 父→子: 写 input.txt；子→父: append output.txt，每轮结束写 `[ROUND END]` 标记；父写 reply.txt 继续；`context.json` 带**绝对路径**（子 cwd 不在 task 目录）。--verbose 模式把原始工具结果 append 到 output，让父可直接审查数据。 | Agent 工具返回是一次性的，看不到中间过程。在 `.claude/skills/subagent-io/` 里约定此协议，配合 Monitor 工具 tail subagent output，实现"派发后仍可观察"。 | ~5h |

### P2 — Reference Only (5 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **Minimal 9-tool surface + code_run 扩展** | 只暴露 9 个原子工具 + code_run 可动态装包扩展能力。 | 我们已有 20+ 内置工具 + MCP 生态，minimal 不是我们的定位。但"任何新能力先走 code_run 验证，稳定后再注册工具"的演化路径值得记住。 |
| **Model-specific tool schema (`_cn` 后缀)** | GLM/MiniMax/Kimi 用 `tools_schema_cn.json`；Claude 用默认。按模型名切换 schema。 | 我们只跑 Claude，但若未来多 provider，这是低成本适配手段。 |
| **MixinSession 虚拟 LLM 合成** | 把多个 backend 组成一个 "mixin" 虚拟客户端，共享 history，支持 fallback/rotation。 | 我们不需要多 provider 聚合，且 Claude Code 路由由平台处理。概念可借用到其他 SDK 场景。 |
| **Reflect 模式 hot-reload** | check() 返回 task 字符串即触发；check.py mtime 变化时 `spec.loader.exec_module` 热重载。开发期体验好。 | 我们有 cron skill/自动 agent，reload 粒度不一样。若未来做"持续监控 + 条件触发"可参考。 |
| **Skill = .md + .py 混居在 memory/** | L3 不区分"工作流文档"和"工具脚本"，都在 memory/ 下，文件命名 `*_sop.md` / `*.py`。 | 我们严格分离 `.claude/skills/` 和 `SOUL/public/prompts/`，混居会破坏 skill routing。但"skill 可以包含可执行代码"这点值得我们的 skill 系统考虑（当前 skill 只能是 markdown）。 |

## Comparison Matrix (P0)

| Capability | Their impl | Our impl | Gap size | Action |
|-----------|-----------|---------|----------|--------|
| Turn-count escalation | `turn_end_callback` turn%7/10/35 注入 [DANGER] | 无；只有 max_turns 上限 | **Large** | Steal (P0-1) |
| Non-tool-call interception | `do_no_tool` handler（拦截空/截断/"完成"无 VERIFY）| verification-gate 是 prompt 级 | **Medium-Large** | Enhance with hook-level interception (P0-2) |
| Live subagent intervention | `_stop/_keyinfo/_intervene` 文件通道 | 派发后不可改 | **Large** | Steal (P0-3) |
| Plan-mode completion gate | `_check_plan_completion` 数 `[ ]` + VERDICT 必需 | TodoWrite + 主 agent 自验证 | **Medium** | Enhance with subagent verify (P0-4) |
| Memory write constraint | 4 公理 + file_access_stats | R42 evidence tiers | **Small-Medium** | Enhance, not replace (P0-5) |
| Completion verification | 独立 subagent + 对抗性 verify_sop.md | verification-gate skill（同一 agent）| **Medium** | Enhance (part of P0-4) |

## Gaps Identified

按六维度映射：

- **Security/Governance**: 我们缺**引擎级硬拦截**。verification-gate、plan 约束都停留在 prompt 层——agent 可以忽略。GenericAgent 把拦截挪到 `do_no_tool` / `turn_end_callback`（hook 等价物），不依赖模型合作。
- **Memory/Learning**: 我们有 evidence tiers 但无**访问热度统计**（GC 决策缺数据）、无 **Sanctity 规则**（理论上 archive.md 可能丢内容）、无**被动晋升提示**（读 skill 不触发内化）。
- **Execution/Orchestration**: 我们的 Agent 派发是 "fire-and-forget"，**无中途干预通道**。对长 steal/debug 任务来说，跑偏即废。
- **Context/Budget**: 我们当前 compact 是整包操作。**缺 tag 粒度选择性压缩**（如只塌缩老的 `<thinking>` 而保留 tool_use）。
- **Failure/Recovery**: 我们无 **turn-based 节奏惩罚**。连跑 20 轮无进展既不会被打断也不会被强制换策略。
- **Quality/Review**: 我们的 verification 是主 agent 自验证。**缺独立对抗验证 subagent** + **verify_sop.md 那种"识别合理化借口"的清单式免疫**。

## Adjacent Discoveries

- **Sliding-window history merge 算法**（`compress_session._merge_history_blocks`）：滚动窗口 + LCS suffix-prefix 对齐重建完整序列。可迁移到 compiler/ 的 session 归档、或任何"只能拿到部分 overlap 视图"的合并场景。
- **socket bind 作进程互斥锁**：`_lock = socket(AF_INET).bind(...)` + `try _lock except NameError` 对付热重载。这是最简 singleton 实现，比 pidfile 干净（进程挂 socket 自动释放）。
- **verify_sop.md 的"两个失败模式 + 识别合理化借口"结构**：65 行里把对抗性审查者的心理防御写成 checklist。我们的 verification-gate 可以直接 fork 这个清单。
- **`{{file:x:N:M}}` 引用展开**：LLM 构造 new_content 时用引用而非 echo，省 token 且防截断。这个语法本身可以扩展到任何需要"大文本不塞进 LLM 输出"的 tool。
- **105K skill remote semantic search API**：http://fudankw.cn:58787 是个开放端点，skill_search SKILL.md 自述"开箱即用"。对我们这种"skill 数量能轻松爆表"的系统，远程 skill index 值得记录（虽然作为外部依赖 P2）。

## Evolution Loop Map

GenericAgent 的自演化闭环（这是 Self-Evolving System target 的核心交付物）：

```
[用户提交任务]
        ↓
[主 agent 读 L1 索引 → 判断是否匹配已有 SOP]
        ↓ 匹配                      ↓ 不匹配
[按 SOP 执行]              [探索模式：启动 subagent 只读探测]
        ↓                            ↓
[执行完成]                 [规划模式：写 plan.md，主 agent 自检 + ask_user 确认]
        ↓                            ↓
[turn_end_callback 检查]   [执行模式：按 plan.md [ ] 项循环，[D] 委托 subagent]
        ↓                            ↓
[plan [ ] 全部[✓]]          [验证模式：独立 subagent 跑 verify_sop.md → VERDICT]
        ↓                            ↓ FAIL（最多 2 次）
[start_long_term_update]    [修复循环：FAIL 项追加 [FIX]，重新验证]
        ↓                            ↓ PASS
[distillation prompt: 提取  [任务完成]
 行动验证成功的信息]                 ↓
        ↓                            ↓
[file_patch L1/L2（不 overwrite）]
 新增 SOP 到 L3（*_sop.md / *.py）
        ↓
[12h cron: compress_session 把 temp/model_responses 压缩归档到 L4 zip]
        ↓
[L4 all_histories.txt 累积，下次类似任务可 grep 召回]
        ↓
[下次用户提交类似任务 → L1 命中 SOP → 一句话复用]
```

**闭环触发点**：`start_long_term_update` 工具（由 agent 主动调用，非自动）——模型判断任务有"行动验证成功的信息值得记忆"时触发，引导模型按 memory_management_sop.md 做最小 patch 更新。**关键约束**：禁止 overwrite、禁止 code_run 改记忆（只能 file_patch），错误成本低到可以放手让模型自主更新。

**护栏**：
- 4 记忆公理（Action-Verified / Sanctity / No Volatile / Minimum Pointer）防止模型把幻觉写进记忆。
- plan 模式的 `[VERIFY]` subagent 是能力成长的质量闸——没通过 VERIFY 的执行路径不会写进 L3。
- L4 压缩 dry_run 默认 + 2h 活跃保护 + 夹包 dedup 防止 archive 破坏正在用的 session。

## Meta Insights

1. **"Prompt 写不出来的事，就写进引擎"**：GenericAgent 最强的约束（turn cadence / no_tool 拦截 / file_patch 唯一匹配 / plan 完成 gate）全是 **engine-level** 的，不依赖 LLM 配合。sys_prompt 只有 7 行。这正是我们"Hard > soft constraints"方针的极致体现——但我们大部分约束还停留在 CLAUDE.md 的 prompt 层。**下一步应把 Gate Functions（Delete/Reset/Config）真正落到 hook 而非文档**。

2. **状态层在文件系统，运维成本趋零**：所有状态（memory/、temp/{task}/、file_access_stats.json、L4 zip）都是人类可读的文件。对比 LangGraph 的 StateGraph / CrewAI 的 Pydantic State，GenericAgent 运维只需 `ls memory/`。我们有 DB，但 DB 不该是唯一状态——**skill/agent 状态应该继续留在文件里**，只把长期分析/统计进 DB。

3. **Subagent 是主 agent 的上下文管家，不是"小弟"**：`plan_sop.md` 里"主 agent 禁止直接执行环境探测，必须委托 subagent"这条规则——**主 agent 的上下文是最稀缺资源**，任何可能产生大量输出的操作必须让独立 context 吃掉。我们 CLAUDE.md 已经有这个思想（"Subagent heuristic: context rot starts ~300-400k"），但在 skill 层没有硬性规则强制"读 >3 文件 → 委托"。应落地。

4. **对抗性验证不是可选项**：verify_sop.md 开头那句"你的两个失败模式：验证回避、被前80%迷惑"是用第二人称直接对 LLM 说的——这比"请仔细验证"强 10 倍。我们的 verification-gate/SKILL.md 应该抄这个写法：不描述"如何验证"，而是**直接揭穿 LLM 的偷懒模式**。

5. **最有价值的不是代码，是阈值**：7/10/35 turn cadence、L1 ≤30 行、`compressed < 4500B` 跳过归档、`cutoff = 2h` 保护活跃 session、`max_delay = 6h` 防雪崩——这些数字看似随意，其实是 39+ 轮生产迭代出的"刚好能管住 LLM 又不会过度打断"的平衡点。**steal 时抄代码容易，抄阈值才是真偷师**。P0-1 照搬 7/10/35 是有意识的选择。
