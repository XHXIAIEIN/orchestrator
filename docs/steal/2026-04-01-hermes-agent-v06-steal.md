# Round 35b：NousResearch/hermes-agent v0.6 偷师

**来源**: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) v0.6.0 (2026-03-30)
**前置**: Round 21 已偷 Frozen Snapshot / Injection Scanning / Budget Refunding / Output Scanning
**本轮焦点**: v0.5→v0.6 新增的平台化能力 + Skin Engine TUI 系统

---

## 核心洞察

v0.6 的进化方向：**从单 Agent 功能深挖转向平台化基础设施**。

| 维度 | v0.5（Round 21 已偷） | v0.6 新增 |
|------|---------------------|-----------|
| 部署 | 单实例 | Profile 多实例隔离 |
| 协议 | OpenAI 兼容 | + MCP 双向 + ACP 编辑器协议 |
| 平台 | TG/Discord/Slack/WhatsApp/Signal | + Feishu/WeCom/Mattermost/Matrix |
| UX | 固定 CLI 样式 | Skin Engine（YAML 主题 + ASCII art + 动画） |
| 路由 | 单 provider | Ordered Fallback Chain + Cheap/Strong 分流 |
| 持久化 | SQLite sessions | + Session Chaining + Atomic Config Writes |

**与 Orchestrator 的正交性**：
- hermes = 一个 Agent 连 12+ 平台，做「连接宽度」
- Orchestrator = 六部多 Agent 协作，做「执行深度」
- **交汇点**：Skin/TUI 层、MCP 双向、Provider Fallback — 这些不依赖架构路线，直接可偷

---

## 可偷模式（12 个）

### P0 — 立即可实施（6 个）

#### 1. Skin Engine — YAML 驱动的 TUI 主题系统

**hermes 做法**：
- 主题 = YAML 文件，放在 `~/.hermes/skins/`
- 三层分离：`colors`（18+ hex 色值）/ `spinner`（等待动画 + 思考动词）/ `branding`（名称/欢迎语/prompt 符号）
- 缺省值从 `default` skin 继承，用户只需覆盖想改的部分
- Rich markup 支持 ASCII art：`banner_logo` 和 `banner_hero` 字段
- `/skin` 命令即时切换，`config.yaml` 持久化

**8 个内置皮肤**：default（金色）、ares（猩红战神）、mono（灰度）、slate（蓝色开发者）、poseidon（海洋）、sisyphus（灰色苦役）、charizard（火焰）

**Orchestrator 映射**：
- Dashboard 的 TUI 模式（我们之前想做的 ASCII arts）直接参考这套 Skin Engine 架构
- `SOUL/public/skins/` 放主题 YAML，`/skin` 命令切换
- spinner 的 `thinking_verbs` 很有趣 —— ares 用 "forging/marching"、poseidon 用 "charting currents"、sisyphus 用 "pushing uphill" —— 这跟我们的人设系统完美匹配，每个部门可以有自己的 thinking verb
- `banner_hero` 用 Rich markup 渲染 ASCII art，我们可以直接复用

**最小实现**：
```yaml
# SOUL/public/skins/default.yaml
name: orchestrator
description: 六部朝廷主题
colors:
  banner_border: "#CD7F32"    # 朝廷金
  banner_title: "#FFD700"
  ui_accent: "#FFBF00"
  ui_ok: "#4dd0e1"
  ui_error: "#ef5350"
spinner:
  thinking_verbs: ["批阅奏折", "调度六部", "翻阅卷宗", "审理案卷"]
  waiting_faces: ["🏛️", "📜", "⚖️", "🔱"]
branding:
  agent_name: "Orchestrator"
  prompt_symbol: "⚖️"
  welcome: "六部就位，等候差遣。"
  goodbye: "退朝。"
```

#### 2. Cheap/Strong Model Routing — 消息复杂度分流

**hermes 做法**：
- 简单消息（闲聊、短问题）→ cheap model（低延迟低成本）
- 复杂消息（含代码/URL/调试请求）→ strong model
- 关键词检测决定路由，保守策略避免误判
- 配置驱动阈值

**Orchestrator 映射**：
- `llm_router.py` 目前是任务级路由（按部门）。可以加消息级预分流：
  - TG 闲聊 → haiku/小模型
  - 代码任务 → sonnet/opus
- Governor 派单前先做一次 complexity scoring，决定走 fast path 还是 full pipeline

#### 3. Ordered Fallback Provider Chain

**hermes 做法**：
- `config.yaml` 中 `fallback_providers` 有序列表
- 主 provider 报错 → 自动切下一个
- 显式报错（不静默降级）
- Provider 切换时清理 stale 配置（api_mode 等）

**Orchestrator 映射**：
- `llm_router.py` 的 waterfall 已有基础，但没有 ordered fallback
- 加 `fallback_chain: [anthropic, openrouter, local]`
- 辅助任务（scrutiny 评估、compression）独立降级链

#### 4. Session Chaining via parent_session_id

**hermes 做法**：
- 压缩后的 session 通过 `parent_session_id` 链接到原始 session
- 可追溯压缩历史
- 支持 gap analysis（看压缩丢了什么）

**Orchestrator 映射**：
- `events.db` 的 session 管理目前是扁平的
- 加 `parent_session_id` 字段，让 context compaction 后的对话可以回溯
- `.remember/` 系统的 archive 过程也可以用 chaining 追踪

#### 5. Iterative Summary Updates — 迭代压缩不丢信息

**hermes 做法**：
- 再次压缩时，不是从零开始 summarize
- 把上一轮 summary 作为输入，增量更新
- summary 字段记录 "compaction count"
- 每次再压缩保护更多尾部 token

**Orchestrator 映射**：
- `.remember/` 的 recent.md → archive.md 流程目前是单次压缩
- 改为带 compaction count 的增量更新：`recent.md (v3)` = 基于 v2 summary + 新内容
- 防止重要上下文在多轮压缩中被稀释

#### 6. Platform-Specific Prompt Hints

**hermes 做法**：
- 检测来源平台 → 动态修改系统 prompt
- WhatsApp: 禁用 markdown，用 `MEDIA://` 传文件
- Telegram: 命令结构差异
- Discord: embed 格式
- 集中管理平台行为差异

**Orchestrator 映射**：
- Channel 层（TG/WX）目前 prompt 没有平台差异化
- TG 支持 markdown 但 WX 不支持 → 应该在 prompt 中注入平台 hint
- `channel_adapters/` 各适配器加 `get_platform_hints() → str`

---

### P1 — 值得后续实施（4 个）

#### 7. Profile Multi-Instance Isolation

**hermes 做法**：
- `HERMES_HOME` 环境变量隔离整个实例（config/sessions/skills/gateway）
- `hermes profile create/switch/delete/export/import`
- Token Lock 防止两个 profile 用同一个 bot credential
- 每个 profile 独立 systemd service

**Orchestrator 映射**：
- 目前单实例部署。如果需要多环境（dev/prod/test），Profile 隔离有价值
- `ORCHESTRATOR_HOME` 环境变量 + profile 子目录

#### 8. Bidirectional MCP — 既是 Client 又是 Server

**hermes 做法**：
- `mcp_tool.py`（79KB）：作为 MCP client 调用外部 MCP server 的工具
- `mcp_serve.py`：把 Hermes 自身暴露为 MCP server（conversations/messages/events/permissions）
- 双向集成：在 Claude Desktop/Cursor 中直接操作 Hermes

**Orchestrator 映射**：
- 目前只有 MCP client（通过 Claude Code 的 MCP 配置）
- 可以把 Orchestrator 的 events.db / collector 状态 / dashboard 数据暴露为 MCP server
- 让其他 Agent（或 Claude Desktop）直接查询 Orchestrator 状态

#### 9. ACP Protocol — 编辑器集成

**hermes 做法**：
- ACP WebSocket server 暴露给 VS Code / Zed / JetBrains
- Session lifecycle 管理
- Tool exposure + Permission negotiation

**Orchestrator 映射**：
- 目前通过 Claude Code IDE extension 间接集成
- 如果要做独立 IDE 插件，ACP 是现成协议参考

#### 10. Terminal Backend Abstraction — 6 种执行后端统一

**hermes 做法**：
- local / Docker / SSH / Daytona / Singularity / Modal
- Skill 目录挂载到远程后端
- 凭据文件 mtime+size 缓存
- 超时时保留部分输出
- 统一环境变量持久化

**Orchestrator 映射**：
- executor 目前只有 local + Docker。抽象层值得参考
- 特别是「超时保留部分输出」和「凭据缓存」

---

### P2 — 架构参考（2 个）

#### 11. Atomic Config Writes

Gateway 的 config.yaml 用原子写入（write to tmp → rename），防止 crash 时写坏配置。Orchestrator 的 `.env` 和 `docker-compose.yml` 修改也应该用这个模式。

#### 12. Tool Output Pruning Before LLM Compression

压缩前先做一轮无 LLM 的 tool output 裁剪（删冗长输出），再交给 LLM summarize。降低压缩成本。`.remember/` 的 archive 流程可以借鉴。

---

## Skin Engine 深入分析（TUI ASCII Arts 专题）

这是我们之前想做的 TUI ASCII arts，hermes 的实现值得拆解：

### 架构

```
hermes_cli/skin_engine.py     ← 加载 YAML、继承默认值、暴露 API
hermes_cli/display.py          ← Rich Console 渲染、spinner 动画、工具输出
~/.hermes/skins/*.yaml         ← 用户自定义皮肤
hermes_cli/skins/              ← 内置皮肤 YAML
```

### 设计决策

| 决策 | 理由 |
|------|------|
| YAML 而非 JSON | 支持多行 ASCII art、注释 |
| 继承而非全量覆盖 | 用户只改想改的，其他从 default 继承 |
| `/skin` 即时切换 | 不需要重启，session 内生效 |
| Personality ≠ Skin | 人设改语气，皮肤改外观，互不干扰 |
| Rich markup in YAML | `[bold #FF0000]text[/]` 直接嵌入 |

### Spinner 系统特别有意思

```yaml
# ares（战神）的 spinner
spinner:
  thinking_verbs: ["forging", "marching", "besieging", "flanking"]
  wings: ["⟪⚔", "⚔⟫"]

# sisyphus（苦役）的 spinner
spinner:
  thinking_verbs: ["pushing uphill", "enduring the loop", "rolling again"]
  wings: ["⟪🪨", "🪨⟫"]
```

这跟我们的六部人设天然匹配：
- **吏部** spinner: "考核中...", "评审中...", "打分中..."
- **工部** spinner: "编译中...", "构建中...", "测试中..."
- **兵部** spinner: "侦察中...", "部署中...", "扫描中..."
- **礼部** spinner: "排版中...", "润色中...", "校对中..."

---

## 与已有偷师的关联

| 已有模式 | hermes v0.6 验证/增强 |
|---------|---------------------|
| Round 21 Frozen Snapshot | v0.6 没改，验证了设计稳定性 |
| Round 21 Injection Scanning | v0.6 扩展了 unicode 检测（RTL override 等） |
| Round 16 LobeHub 6 维记忆 | hermes 加了 Honcho 用户建模，比纯记忆更深 |
| Round 25 Slash-Command-as-Workflow | `/skin` 命令是好例子：即时生效 + 持久化分离 |
| Round 28b 九段压缩 | hermes 的 Iterative Summary Updates 是工程实现版本 |
| Round 33 Headroom 压缩 | hermes 的 Tool Output Pruning 是轻量版同一思路 |

## 不偷的（以及为什么）

| 模式 | 原因 |
|------|------|
| 431KB 单文件 run_agent.py | 六部制已解决，这是技术债不是设计 |
| 12 平台 gateway adapter | 我们只需要 TG + WX + Claw，不需要 Signal/Matrix/Mattermost |
| Honcho 用户建模 | 外部依赖，我们的 .remember/ + SOUL 系统更自洽 |
| Trajectory/RL 训练 | 不同方向，我们不做 benchmark |
| Codex OAuth fallback | OpenAI 特有，不通用 |

---

## 实施优先级

1. **P0-1: Skin Engine** → 直接做，我们想要的 TUI ASCII arts 终于有现成架构参考了
2. **P0-2: Cheap/Strong Routing** → TG 闲聊不需要 opus，haiku 就够
3. **P0-6: Platform Prompt Hints** → TG vs WX 的 prompt 差异化
4. **P0-5: Iterative Summary Updates** → .remember/ 系统升级
5. **P0-3: Fallback Provider Chain** → llm_router 增强
6. **P0-4: Session Chaining** → events.db schema 改动
