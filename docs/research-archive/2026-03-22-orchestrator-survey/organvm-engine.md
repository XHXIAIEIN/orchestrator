# organvm-engine (meta-organvm)

- **URL**: https://github.com/meta-organvm/organvm-engine
- **语言**: Python | **规模**: 22 模块, 23 CLI 命令组, 590+ 测试
- **评级**: S 级

## 一句话

116+ 仓库、8 个"器官"的 AI 多智能体治理引擎——生物隐喻架构 + 宪法事件总线。

## 可偷模式

### 1. Seed Contract 声明式依赖图 ⭐⭐⭐⭐⭐
每个仓库 `seed.yaml` 声明 produces/consumes/subscriptions。Liskov 式单调性检查——升级后不能删减已有 produces。

→ 每个"部"定义 produces/consumes/subscriptions，事件路由从声明生成而非硬编码。

### 2. Punch-in/Punch-out 协调 ⭐⭐⭐⭐⭐
Agent 开始工作时"打卡"声明操作区域，系统检测冲突。每个 claim 有 TTL（4h），资源权重 light(1)/medium(2)/heavy(3)，总容量 6 单位。

→ 多 agent 并行时的无锁协调。

### 3. Authority Ceiling ⭐⭐⭐⭐⭐
四级权限 READ → PROPOSE → MUTATE → APPROVE。AI agent 天花板是 MUTATE，APPROVE 留给人类。

→ "朕"就是 APPROVE 层，AI 怎么折腾都不能越过。

### 4. Append-Only 哈希链事件日志 ⭐⭐⭐⭐
JSONL + SHA-256 prev_hash 链 + fcntl.flock 排他锁。repair_chain() 修复损坏。

→ run-log.jsonl 加 prev_hash，免费篡改检测。

### 5. Tool Checkout Line ⭐⭐⭐⭐
重型命令（pytest）一次一个，中型（ruff）最多两个，轻型（git status）无限制。5 分钟 TTL 防死锁。

→ Docker 环境多 collector 限流。

### 6. NerveBundle 订阅路由 ⭐⭐⭐
seed.yaml 订阅声明收集成 NerveBundle，支持通配符匹配，按事件类型/订阅者双向索引。

### 7. Agent Handle 命名池 ⭐⭐⭐
每种 agent 类型有主题化词库（claude-forge, gemini-scout）。极大提升可观测性。

### 8. 数据驱动 + 硬编码 Fallback ⭐⭐⭐
状态机优先读配置文件，读不到退化到硬编码。比纯配置或纯硬编码都健壮。
