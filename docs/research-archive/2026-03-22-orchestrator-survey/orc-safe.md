# safethecode/orc

- **URL**: https://github.com/safethecode/orc
- **语言**: TypeScript/Bun | **规模**: 90+ core 模块
- **评级**: B 级

## 一句话

终端原生多 agent 编码编排——Tournament Optimizer + Doom Loop Detection + WorkerBus。

## 可偷模式

### 1. Tournament Optimizer ⭐⭐⭐⭐⭐
可量化优化任务跑 5 阶段锦标赛：每阶段 3-4 条并行路径（conservative/aggressive/creative/systematic），胜者代码注入下一阶段。Golden solution 跨 session 复用。Diminishing returns 检测自动换策略。

### 2. Doom Loop Detection ⭐⭐⭐⭐⭐
双重检测：相同 tool+input 滑动窗口重复 5 次触发 / 同一文件编辑 4 次以上触发。

→ 三省六部"御史台"检查项。

### 3. WorkerBus Artifact 广播 ⭐⭐⭐⭐
一个 agent 完成的文件/API/schema 通知所有订阅者。比 prompt 塞上下文优雅。

### 4. DAG + Phase 执行 ⭐⭐⭐⭐
依赖图拓扑排序，分 phase 并行。硬编码规则：database → backend → frontend → testing。

### 5. Cost-Aware Provider Selection ⭐⭐⭐
按 subtask 复杂度和 role 需求评分，选最便宜且够用的 provider+model。

## 局限
- Orchestrator class 100+ 成员变量 God Object
- 正则领域检测脆弱
- 全内存态，crash 丢状态
