# Round 23 P1-4: Claude Code Buddy + AutoDream — 架构模式深挖

> 来源: Kuberwastaken/claude-code mirror (npm sourcemap 泄露)
> 目标文件: buddy/{types,companion,sprites,prompt,CompanionSprite,useBuddyNotification}.ts + services/autoDream/* + tasks/DreamTask/*
> 分析日期: 2026-04-01

---

## 系统一：Buddy Companion（确定性 Gacha 宠物系统）

### 1. 架构模式：Deterministic Gacha via Seeded PRNG

**核心抽象**：用 `hash(userId + salt)` 作为种子，通过 Mulberry32 PRNG 确定性生成宠物属性。每个用户永远只会 roll 出同一只宠物——不是随机，是命运。

```
userId → hashString(userId + SALT) → mulberry32(seed) → rng()
  → rollRarity(rng)     // 加权抽取: common 60 / uncommon 25 / rare 10 / epic 4 / legendary 1
  → pick(rng, SPECIES)  // 18种: duck/goose/blob/cat/dragon/...
  → pick(rng, EYES)     // 6种: ·/✦/×/◉/@/°
  → pick(rng, HATS)     // 8种 (common = none, 其他随机)
  → rng() < 0.01 → shiny
  → rollStats(rng, rarity) → { DEBUGGING, PATIENCE, CHAOS, WISDOM, SNARK }
```

**关键设计决策**：

- **Bones vs Soul 分离**：`CompanionBones`（种族/稀有度/属性）从 hash 确定性推导，永不持久化。`CompanionSoul`（名字/性格，由 Claude 模型在首次 hatch 时生成）才持久化到 config。这样 SPECIES 数组可以随便改、存储格式随便迁移、用户编辑 config 也伪造不了稀有度。
- **Roll 缓存**：`rollCache` 单 entry 缓存（key=userId+salt），因为 500ms sprite tick / 每次按键 PromptInput / 每轮 observer 都调用同一个 userId。
- **Salt = `'friend-2026-401'`**：版本锁定 salt，防止不同版本 roll 出不同结果。

**P0 可偷模式：Bones-Soul Split Persistence**

> 状态中"可确定性重算的部分"永不持久化，只存"不可重现的部分"（模型生成的人格）。这消除了一整类的状态迁移 bug。

### 2. 门控/激活逻辑：Feature Flag + 时间窗口

```typescript
// 四层门控
feature('BUDDY')                      // 编译期特性标志（bun:bundle tree-shake）
isBuddyTeaserWindow()                 // 本地日期 2026/4/1-7（非 UTC，24h 滚动制造 Twitter buzz）
isBuddyLive()                         // 2026/4 月以后永久开启
getGlobalConfig().companionMuted       // 用户手动静音
```

**P0 可偷模式：Rolling Timezone Launch Window**

> 用本地日期而非 UTC 做时间窗口 → 全球用户在自己的 4/1 进入窗口 → 24 小时滚动式 buzz 而非单个 UTC 午夜峰值。同时降低 soul-gen API 负载峰值。

### 3. 数据流

```
[启动] → useBuddyNotification → 检测是否已 hatch
  ├─ 未 hatch + 在 teaser window → 显示彩虹 "/buddy" 通知（15s 自动消失）
  └─ 已 hatch → CompanionSprite 渲染

[CompanionSprite 渲染循环 - 500ms tick]
  → getCompanion() → roll(userId).bones + stored soul
  → IDLE_SEQUENCE 帧选择（0,0,0,0,1,0,0,0,-1,0,0,2,0,0,0）
    - frame 0 = 休息, 1-2 = fidget, -1 = 眨眼
  → reaction 存在时 → 兴奋帧循环 (tick % frameCount)
  → pet 触发 → 心形粒子效果 (PET_HEARTS, 2.5s burst)

[语音泡泡]
  → companionReaction (AppState 注入) → SpeechBubble 组件
  → BUBBLE_SHOW=20 ticks (~10s) 后消失
  → 最后 FADE_WINDOW=6 ticks (~3s) 做渐隐

[窄终端适配]
  → columns < 100 → 退化为单行 face + 名字/短引用
  → companionReservedColumns() 告诉 PromptInput 预留列宽
```

**P0 可偷模式：Graceful Degradation by Terminal Width**

> 不是"小屏幕就不显示"，而是退化到更紧凑的形态。全屏模式下 bubble 浮在 scrollback 上方（不占宽度），非全屏时内联占位。

### 4. ASCII Art 渲染引擎

**sprites.ts** — 18 种 species × 3 帧的 ASCII 矩阵：

```
每帧 5 行 × 12 宽
{E} 占位符 → 运行时替换为 eye 字符
line 0 = hat slot（空白时替换为帽子，fidget 帧用于烟雾/天线等时保留）
帧高度一致性检查：只有所有帧的 line 0 都是空的才会裁剪
```

**P1 可偷模式：Parameterized ASCII Sprite System**

> 用占位符模板 + 属性注入实现组合爆炸（18 species × 6 eyes × 8 hats = 864 种外观），而不是预渲染所有组合。

### 5. Prompt 注入（companion 如何影响 AI 对话）

```typescript
companionIntroText(name, species):
  "A small ${species} named ${name} sits beside the user's input box
   and occasionally comments in a speech bubble. You're not ${name} —
   it's a separate watcher."
```

**关键约束**：不是让 Claude 扮演宠物——明确说"你不是它"。宠物通过 `companionReaction` 在 AppState 注入，主模型被指示"当用户叫它名字时，让开"。

**P1 可偷模式：Companion-as-Separate-Entity Prompt Pattern**

> 避免人格分裂：宠物是独立 watcher，主模型不模拟它。reaction 通过状态注入而非模型生成。

---

## 系统二：AutoDream（背景记忆整合）

### 1. 架构模式：Tiered Gate → Forked Subagent

AutoDream 是一个后台整理记忆文件的系统。核心抽象：**在用户空闲时 fork 一个子 agent 执行 /dream prompt，整理 MEMORY.md 和话题文件**。

```
用户正常对话
  ↓ (每轮结束时 stopHooks 触发)
executeAutoDream()
  → isGateOpen() 多层检查
  → Time Gate: hours since last consolidation >= minHours (默认 24h)
  → Scan Throttle: 距上次扫描 >= 10min
  → Session Gate: 足够多的新 session (默认 5 个)
  → Lock: 无其他进程在做 dream
  → fork 子 agent 执行 consolidation prompt
  → 完成后更新 lock mtime (= lastConsolidatedAt)
```

### 2. 门控/激活逻辑：五层 Gate（最廉价的先检查）

```
Gate 1: isGateOpen()
  - !KAIROS 模式（KAIROS 有自己的 disk-skill dream）
  - !远程模式
  - isAutoMemoryEnabled() (env/settings 多层判断)
  - isAutoDreamEnabled() (settings.json 覆盖 → GrowthBook tengu_onyx_plover)

Gate 2: Time Gate
  - stat(lockFile).mtime → hours since >= minHours
  - 每轮成本: 一次 stat()

Gate 3: Scan Throttle
  - 内存变量 lastSessionScanAt
  - 防止 time-gate 通过后 session-gate 每轮重复扫描

Gate 4: Session Gate
  - listSessionsTouchedSince() → 扫描 JSONL 文件 mtime
  - 排除当前 session（mtime 永远新鲜）
  - sessionIds.length >= minSessions

Gate 5: Lock Acquisition
  - PID 文件 + 活跃度检测
  - 双写竞态保护（write PID → re-read verify → 不匹配则退让）
```

**P0 可偷模式：Cheapest-First Gate Chain**

> 每一层 gate 按计算成本排序。stat() 比文件列表便宜，文件列表比锁获取便宜。大多数调用在最廉价的 gate 就被拦截。

**P0 可偷模式：Lock File mtime = State**

> lock 文件的 mtime 就是 `lastConsolidatedAt` 时间戳。不需要额外的状态文件——文件系统元数据即状态。失败时 `utimes()` 回滚 mtime，崩溃时通过死 PID 检测回收。

### 3. 数据流

```
[输入]
  - memoryRoot: ~/.claude/projects/<sanitized-git-root>/memory/
  - transcriptDir: session JSONL 文件目录
  - sessionIds: 自上次整合后有变动的 session 列表

[Consolidation Prompt - 4 阶段]
  Phase 1 - Orient: ls memory dir, 读 MEMORY.md, 浏览现有话题文件
  Phase 2 - Gather: 按优先级搜集信号（daily logs > 过期记忆 > transcript grep）
  Phase 3 - Consolidate: 写/更新记忆文件，合并而非创建重复
  Phase 4 - Prune: 更新 MEMORY.md 索引（<=200行 <=25KB），删除过时条目

[工具约束]
  - Bash 限制为只读命令 (ls/find/grep/cat/stat/wc/head/tail)
  - FileEdit / FileWrite 允许（写记忆文件）
  - canUseTool = createAutoMemCanUseTool(memoryRoot)

[输出]
  - 更新后的 memory/ 目录文件
  - DreamTask 状态跟踪（UI 可见的 footer pill + Shift+Down dialog）
  - appendSystemMessage: "Improved N memories" 内联消息

[失败处理]
  - 用户手动 kill → abortController.abort() + 回滚 lock mtime
  - fork 崩溃 → rollbackConsolidationLock(priorMtime) + scan throttle 做 backoff
  - 已 abort 不覆盖状态 → 防止 double-rollback
```

### 4. 非显而易见的实现技巧

#### 4a. Closure-Scoped State (Not Module-Level)

```typescript
export function initAutoDream(): void {
  let lastSessionScanAt = 0  // closure 内部变量
  runner = async function runAutoDream(...) { ... }
}
```

状态（`lastSessionScanAt`）封在 `initAutoDream()` 闭包里而非模块顶层。好处：测试时 `beforeEach` 调用 `initAutoDream()` 就能得到干净闭包，无需 mock 模块变量。

**P1 可偷模式：Closure-Scoped Agent State for Testability**

#### 4b. Lock File 双写竞态保护

```typescript
// 两个回收者同时写 → 最后一个赢 PID
await writeFile(path, String(process.pid))
// 输者在重读时退出
const verify = await readFile(path, 'utf8')
if (parseInt(verify.trim(), 10) !== process.pid) return null
```

无需 flock/advisory lock——文件系统原子性 + 后验校验 = 穷人版分布式锁。

**P0 可偷模式：Optimistic Lock via Write-Then-Verify**

#### 4c. DreamTask 做 UI 透明化

Dream agent 在后台跑，但通过 Task 注册系统暴露到 UI：
- footer pill 显示 "dreaming"
- Shift+Down 打开 DreamDetailDialog 看实时 turn 输出
- 只保留最近 30 turns（滑动窗口）
- phase 不做 prompt 阶段解析，只在首个 Edit/Write tool_use 出现时从 `starting` 翻转到 `updating`

**P1 可偷模式：Background-Agent-as-Visible-Task**

#### 4d. GrowthBook Feature Flag 架构

```typescript
// config.ts — 最薄入口，只读 enabled 状态
// autoDream.ts — 调度阈值从同一 flag 读
const raw = getFeatureValue_CACHED_MAY_BE_STALE<Partial<AutoDreamConfig>>('tengu_onyx_plover', null)
```

一个 GrowthBook feature flag 同时控制 enabled 开关和 minHours/minSessions 阈值。config.ts 做最薄导出（UI 组件可以 import 而不拖入整个 autoDream 依赖链）。

**P1 可偷模式：Thin Config Leaf Module**

#### 4e. Memory Path 安全验证

`paths.ts` 对内存目录路径做了严格验证：
- 拒绝相对路径、根路径、UNC 路径、null 字节
- `~/ `展开有陷阱检测（`~/` → $HOME 太危险）
- projectSettings（repo 内 .claude/settings.json）被**故意排除**——恶意 repo 可以设 `autoMemoryDirectory: "~/.ssh"` 获取写权限

**P0 可偷模式：Untrusted-Source Setting Exclusion**

> 从 repo 提交的配置文件中排除可能造成安全漏洞的设置项。只信任 policy/local/user 级别。

---

## 对 Orchestrator 的适用性分析

### 直接可偷（P0）

| 模式 | 来源 | Orchestrator 适配方案 |
|------|------|-----------------------|
| **Cheapest-First Gate Chain** | autoDream gates | 所有后台任务（采集器/分析器/维护）统一用多层 gate：config check → time check → resource check → lock |
| **Lock File mtime = State** | consolidationLock.ts | Docker volume 内的 lock 文件可以替代 Redis/SQLite 做简单的"上次运行时间"跟踪 |
| **Optimistic Lock via Write-Then-Verify** | consolidationLock.ts | 多容器竞争同一任务时，用文件写+后验代替分布式锁 |
| **Bones-Soul Split Persistence** | companion types | Agent 人格（SOUL）vs 运行时状态：只持久化不可重算的部分 |
| **Untrusted-Source Setting Exclusion** | paths.ts | .claude/settings.json 已有信任层级，照搬：repo 内配置不能覆盖安全相关设置 |
| **Rolling Timezone Launch** | useBuddyNotification | 功能上线时用本地时间窗口替代 UTC 开关 |

### 可改造后偷（P1）

| 模式 | 来源 | 改造方向 |
|------|------|----------|
| **Closure-Scoped Agent State** | initAutoDream | Docker 容器内的采集 agent 用类似闭包初始化模式，方便测试 |
| **Background-Agent-as-Visible-Task** | DreamTask | Dashboard 上显示后台 dream/maintenance 任务的实时状态 |
| **Thin Config Leaf Module** | config.ts | 将"是否启用"逻辑隔离到薄模块，UI 不拖入执行依赖 |
| **Parameterized ASCII Sprite** | sprites.ts | Bot 回复中的 ASCII 表情/状态指示器可以用模板 + 属性注入 |
| **4-Phase Consolidation Prompt** | consolidationPrompt.ts | Memory 整理 prompt 的 Orient→Gather→Consolidate→Prune 四阶段结构直接可用于 SOUL 自省 |
| **Graceful Width Degradation** | CompanionSprite | Dashboard 移动端适配：不是隐藏组件，而是退化到紧凑形态 |

### 需要注意的差异

1. **AutoDream 跑在 Node.js 单机**——我们是 Docker 多容器，lock 策略需要考虑 volume mount 的文件系统语义
2. **Buddy 依赖 Ink (React 终端 UI)**——我们的 Dashboard 是 Web，sprite 系统需要用 CSS/Canvas 替代
3. **GrowthBook 远程 feature flag**——我们可以用 Docker env + settings.json 两层替代
4. **ForkedAgent 是 Node.js child_process**——我们的等价物是 Agent SDK subagent 或 Docker exec

---

## 总结：6 个 P0 + 6 个 P1 = 12 个可偷模式

最有价值的三个：

1. **Cheapest-First Gate Chain** — 后台任务调度的标准模式，立即可用
2. **Lock mtime = State** — 零依赖状态追踪，比 SQLite row 更轻
3. **4-Phase Consolidation Prompt** — Dream prompt 的 Orient→Gather→Consolidate→Prune 是记忆整理的通用框架，直接套用到 SOUL 自省
