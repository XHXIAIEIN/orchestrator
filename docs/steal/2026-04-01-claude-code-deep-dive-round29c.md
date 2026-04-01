# Round 29c：claude-code-deep-dive 源码深挖

> Source: https://github.com/tvytlx/claude-code-deep-dive
> 方法：从 `@anthropic-ai/claude-code` npm 包 `cli.js.map` 还原 4756 个源码文件后系统性拆解
> 与 Round 28a/28b/29b 交叉去重后的 **净增量**

---

## 与已有偷师的关系

| 已有 Round | 覆盖范围 | 本轮增量 |
|-----------|---------|---------|
| 28a (npm逆向) | Gate Chain, Address Registry, Unified Executor | 本轮补充实现细节，无重复 |
| 28b (system prompts) | Coordinator Synthesis, Verification Agent, Compact, Cache Boundary | 本轮补充 Coordinator 实现代码 |
| 29b (6子系统深逆) | QueryEngine, Bridge, Memory, Task, Services, Plugin (84模式) | 本轮从源码层补充 8 个全新子系统 |

**本轮净增**: 12 个新模式（README 分析与已有高度重叠，价值在 extracted-source 扫描）

---

## 新模式清单

### P0 — 必偷（4 个）

#### 1. DreamTask 后台记忆整理
- **来源**: `src/tasks/DreamTask/DreamTask.ts`
- **机制**: 主会话不中断，fork 出后台 agent 执行记忆整理（orient → gather → consolidate → prune 四阶段）
- **关键细节**:
  - `MAX_TURNS = 30`，UI 只显示最近轮次
  - 整理锁基于 `priorMtime`，kill 时回滚锁防止并发竞争
  - 阶段转换信号：首次 Edit/Write 工具调用 = 从 'starting' 进入 'updating'
  - 完成后 `notified: true`，通知只走 UI 不打扰模型
- **可偷方向**: experiences.jsonl 自动整理 — 每 N 轮对话后台 fork 一个 DreamTask 整理记忆碎片

#### 2. Team Memory 分域作用域
- **来源**: `src/memdir/teamMemPaths.ts` (11KB)
- **机制**: 记忆分两层目录 — 私有 (`~/.claude/memories/{project}/`) + 团队 (`~/.claude/team-memories/{team}/{project}/`)
- **关键细节**:
  - 查找顺序：团队记忆优先，私有记忆为 fallback
  - Feature gate: `feature('TEAMMEM')`
  - 团队成员共享上下文但不泄露私人笔记
- **可偷方向**: SOUL/private vs SOUL/public 已有雏形，但缺少"团队记忆"概念 — 可用于多 agent 协作场景（如 ElderCouncil 共享审议记忆）

#### 3. Notification 优先级队列 + 折叠
- **来源**: `src/context/notifications.tsx` (33KB)
- **机制**: 通知系统支持 4 级优先级 + key-based 失效 + 折叠回调
- **关键细节**:
  - 优先级: `'low' | 'medium' | 'high' | 'immediate'`
  - `invalidates?: string[]` — 新通知可废弃旧通知
  - `fold?: (accumulator, incoming) => merged` — 同 key 通知合并（如多个编译错误合并成一条）
  - `immediate` 优先级打断当前队列
- **可偷方向**: Dashboard 通知系统改造 — 当前 events 都是平级，缺少优先级和折叠

#### 4. 主会话后台化（Ctrl+B×2）
- **来源**: `src/tasks/LocalMainSessionTask.ts` (15KB)
- **机制**: 用户在查询运行中按两次 Ctrl+B，查询转入后台继续，UI 腾出来接新输入
- **关键细节**:
  - 复用 LocalAgentTaskState，agentType = 'main-session'
  - Task ID 前缀 's'（agent 用 'a'）以区分
  - 完成后通过 notification 回到主线程
  - 可通过 Shift+Down 对话框查看
- **可偷方向**: Governor 长任务执行时允许"搁置"当前任务去处理紧急请求，任务完成后通知回调

---

### P1 — 值得偷（4 个）

#### 5. Buddy 确定性宠物系统（Hash 种子）
- **来源**: `src/buddy/` (companion.ts + types.ts + CompanionSprite.tsx)
- **机制**: 用 `hash(userId + SALT)` 生成 Mulberry32 PRNG 种子，确定性生成宠物属性
- **关键细节**:
  - **Bones**（骨骼，确定性）: species / eye / hat / rarity / shiny / stats — 每次从 hash 重新生成
  - **Soul**（灵魂，持久化）: name / personality — 存 config，与 bones 合并
  - 稀有度权重: common 60% / uncommon 25% / rare 10% / epic 4% / legendary 1%
  - 属性：一个峰值 stat + 一个弱项 stat，稀有度提升下限
  - `roll()` 按 userId 缓存，避免每帧重算（sprite 500ms tick）
- **可偷方向**: Orchestrator 人格系统的"情绪状态"可以用类似的确定性种子 — 基于时间+事件 hash 生成当日心情，避免完全随机

#### 6. Output Style 模板系统
- **来源**: `src/outputStyles/loadOutputStylesDir.ts` (3KB)
- **机制**: `.claude/output-styles/` 下放 .md 文件，filename = style name，frontmatter = 元数据，content = prompt
- **关键细节**:
  - Frontmatter: `name`, `description`, `keep-coding-instructions` (bool), `force-for-plugin`
  - 项目级样式覆盖用户级
  - Memoized + cache invalidation
- **可偷方向**: 我们的 output style 已通过 hook 注入，但缺少文件级模板 — 可以让不同任务类型自动切换 style

#### 7. 原生文件索引（Pure TS 降级）
- **来源**: `src/native-ts/file-index/index.ts` (12KB)
- **机制**: 当 NAPI 模块不可用时，用纯 TypeScript 实现 nucleo 兼容的模糊搜索
- **关键细节**:
  - 评分: `SCORE_MATCH=16, BONUS_BOUNDARY=8, BONUS_CAMEL=6`
  - 异步分块: 每 ~4ms yield 一次事件循环（27万+ 文件列表不阻塞）
  - 结果缓存: 最多 100 条，重复查询 5-10x 加速
  - 测试路径惩罚: 1.05× 分数乘数（上限 1.0）
- **可偷方向**: RAG 检索结果排序可以参考 bonus 机制（boundary/camel/slash 加分）

#### 8. Remote Permission Bridge（合成工具桩）
- **来源**: `src/remote/remotePermissionBridge.ts` (2KB)
- **机制**: 远程 agent 请求使用本地未知工具时，创建合成 AssistantMessage + Tool 桩，路由到 FallbackPermissionRequest
- **关键细节**:
  - 防止本地/远程工具集不一致导致权限系统崩溃
  - WebSocket 重连: 2s delay, 5 max attempts; 4003=auth 永久断开, 4001=session-not-found 给 3 次机会
- **可偷方向**: multi-agent 场景下 agent 请求未注册工具时的降级策略

---

### P2 — 了解即可（4 个）

#### 9. Upstream Proxy WebSocket 隧道
- **来源**: `src/upstreamproxy/relay.ts` (15KB)
- **机制**: CCR 容器出站流量通过 CONNECT→WebSocket 隧道，Protobuf 编码 (`UpstreamProxyChunk`)
- **细节**: MAX_CHUNK_BYTES=512KB, PING=30s, NO_PROXY 包含 loopback/RFC1918/IMDS/GitHub/npm/PyPI
- **评估**: CCR 特有，我们不需要

#### 10. Speculation 边界类型
- **来源**: `src/state/AppStateStore.ts` (22KB)
- **机制**: 预测执行边界检测: `complete | bash | edit | denied_tool`
- **细节**: WrittenPathsRef 用 mutable ref 避免每条消息 array spread
- **评估**: UI 优化细节，与我们架构无关

#### 11. Voice Mode 平台检测链
- **来源**: `src/voice/voiceModeEnabled.ts` + `vendor/audio-capture-src/`
- **机制**: NAPI fallback: native → PulseAudio (Linux) → AVFoundation (macOS) → WASAPI (Windows)
- **细节**: GrowthBook kill-switch, OAuth-only (no API keys), macOS TCC 权限状态 4 级
- **评估**: 语音功能方向参考

#### 12. Coordinator Mode 实现细节
- **来源**: `src/coordinator/coordinatorMode.ts` (19KB)
- **机制**: 内部工具 CreateTeam/DeleteTeam/SendMessage/SyntheticOutput，worker 不可见
- **细节**: 模式不匹配检测 `matchSessionMode()`，resume 时翻转 env var
- **评估**: 28b 已记录 Coordinator Synthesis 纪律，这是实现层补充

---

## README 分析评估

tvytlx 的 1100 行 README 是目前公开最系统的 Claude Code 架构分析，覆盖 10 大主题。但与我们已有的 Round 28/29 系列高度重叠：

| README 章节 | 我们的覆盖 | 增量 |
|------------|-----------|------|
| §1 研究范围 | ✅ 28a 已确认 4756 文件 | 无 |
| §2 源码结构全景 | ✅ 28a 模块清单 | 无 |
| §3 系统提示词总装 | ✅ 28b Cache Boundary + Assembly | 无 |
| §4 Prompt 全量提取 | ✅ 28b 16 模式 | 无 |
| §5 Agent Prompt | ✅ 28b Verification Agent + 29b Agent 调度 | fork cache 细节有补充 |
| §6 Agent 调度链 | ✅ 29b QueryEngine + Task 系统 | runAgent 资源清理链有补充 |
| §7 Skill/Plugin/Hook/MCP | ✅ 28a/28b 均覆盖 | 无 |
| §8 权限与工具执行链 | ✅ 28a Gate Chain | resolveHookPermissionDecision 语义有补充 |
| §9 护城河分析 | ✅ 28b 已有类似总结 | 无 |
| §10 文件索引 | ✅ 作为参考 | 无 |

**结论**: README 价值在于中文系统性整理（适合分享），但对我们的偷师增量有限。真正的增量来自 extracted-source 里 29b 未扫到的子系统。

---

## 总结

| 级别 | 数量 | 核心主题 |
|------|------|---------|
| P0 | 4 | DreamTask 后台整理 / Team Memory 分域 / 通知折叠 / 主会话后台化 |
| P1 | 4 | Buddy 确定性种子 / Output Style 模板 / 文件索引降级 / Remote Permission Bridge |
| P2 | 4 | Upstream Proxy / Speculation边界 / Voice平台链 / Coordinator实现 |
| **合计** | **12** | **净增 12 模式（去重 Round 28/29 后）** |

与 Round 29b 的 84 模式互补，共同构成 Claude Code 最完整的逆向知识库。
