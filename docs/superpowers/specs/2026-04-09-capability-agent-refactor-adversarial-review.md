# Capability + Agent Refactor 设计对抗性审查

**日期**: 2026-04-09  
**审查对象**: `docs/superpowers/specs/2026-04-08-capability-agent-refactor-design.md`  
**审查方式**: 通读全文并交叉核对当前代码中的 `intent.py`、`routing.py`、`dispatcher.py`、`governor.py` 调用契约。  
**结论摘要**: 这份设计已经比早期版本完整得多，但仍然存在明显的“抽象层叠过厚、保护机制补丁化、迁移面过宽、调用侧认知负担偏高”的问题。它不是不能做，而是以 v1 的复杂度来看，设计已经逼近“只有作者自己完全理解”的危险区间。

---

## 总体判断

这份方案最大的优点是把 `WHO` 和 `WHAT` 分离，方向上是对的。最大的缺点是为了把这个分离做“完备”，同时引入了过多横切概念：

- capability
- agent
- specialization
- intent
- active_capabilities
- authority_cap
- profile
- model_floor
- override stack
- FSM
- dispatcher phase 0.5
- ad-hoc mode
- scenario/reducer
- registry_version

这些概念单独看都“有道理”，合在一起就形成了非常高的系统解释成本。对一个还在迁移中的系统来说，这会直接转化为实现偏差、兼容性漏洞和消费者误用。

---

## 1. 不合理或过度设计的决策

### 1.1 v1 同时引入太多维度，配置表面远大于收益

本设计不是简单把 `department` 重命名为 `agent`。它在一次重构里同时重做了：

- 角色模型
- 权限模型
- prompt 组装模型
- rubric 合成模型
- FSM
- 并发调度
- ad-hoc 调度
- 热重载版本钉住
- 数据迁移与双读兼容

这对 v1 来说过重。实际结果是：每个局部问题都被设计成一个新抽象，而不是优先压缩系统自由度。越多“可配置层”，越难验证“默认路径是否始终正确”。

### 1.2 `active_capabilities` 只过滤 prompt/rubric，是一个明显的补丁型设计

文档已经经历过一次“active_capabilities 过滤全链路”再回退为“只过滤 prompt/rubric”的反复。这说明这里本身就不是稳定设计。

当前方案的问题是：

- prompt 告诉模型“你现在只是在做 collect”
- 但 tools/authority/model 仍可能来自全部 capability
- 然后又额外补一个 `restrict_tools`

这会让系统出现“模型看到的身份/说明”和“运行时真实权限”不一致。  
这不是一个优雅的分层，而是用更多显式参数去修补先前抽象造成的裂缝。

### 1.3 `model_floor` / profile ceiling / intent.model 的优先级体系过于复杂

模型选择现在要同时理解：

- capability 合成上限
- capability 的 `model_floor`
- agent override
- intent explicit model
- profile ceiling

这会让“为什么这次用了 opus”很难被快速解释。  
如果一个系统需要专门增加 `_trace` 字段才能解释自己怎么决策，通常说明决策维度已经超出日常维护舒适区。

### 1.4 Dispatcher Phase 0.5 是职责污染

文档把 Fact-Expression Split 从 FSM 挪到 dispatcher，理由是 executor 无状态、没有 `resume()`。这个修正避免了一个错误实现，但没有解决更根本的问题：  
**dispatcher 本应是调度控制面，现在却承担了领域工作流编排。**

结果是：

- dispatcher 既负责 enrichment/gating
- 又负责 split 判定
- 又创建子任务
- 又处理 semaphore/scrutiny
- 又决定何时短路主流程

这会让 dispatcher 成为新的巨型核心模块。长期看，它会比旧的硬编码部门逻辑更难拆。

### 1.5 Ad-hoc mode 占比写成 10%，但设计复杂度接近一整套子系统

ad-hoc 引入了：

- capability 覆盖匹配
- 单 agent / 多 agent 分流
- 最小权限降级
- 必要时审批
- scenario 自动命中
- 串行 / 并行 / reducer
- 审计日志

如果这真的是 10% 的边缘路径，这个复杂度不划算。  
如果它其实会被大量调用，那它又不该只是“补充模式”，而应该成为一等 API，并获得更清晰的调用契约。

### 1.6 L2 override 标为 RESERVED，但整份设计仍保留了它的心智负担

虽然正文已经把 L2 标成保留层，但它依然存在于叙事结构里。这会产生两个问题：

- 实现者会下意识为 L2 预留接口和分支
- 调用方会误以为未来还会有 blueprint 层插入当前语义

对 v1 来说，更好的方案是彻底删除这一层叙事，只在扩展文档里提及，不该继续出现在主设计的核心决策模型中。

---

## 2. 从旧架构迁移时的回归风险

### 2.1 这是“名义上有 feature flag，实际上仍接近 Big Bang”的迁移

文档写了 `ORCHESTRATOR_ARCH=v1/v2`，但真正的切换面是整条链：

- `intent.py`
- `routing.py`
- `dispatcher.py`
- `governor.py`
- `review_dispatch.py`
- `executor_prompt.py`

再加上 storage、budget、channel、jobs、evolution 等 40+ 文件。  
这意味着它不是普通的“新旧并存”，而是“整个调用链和大量外围系统同时切换”。一旦某个低频路径漏改，回归不是局部异常，而是 silent misroute。

### 2.2 迁移计划缺少明确的 dual-write 阶段

文档强调 dual-query，但对写路径描述不足：

- 新代码写 `agent`
- 旧代码写 `department`
- 迁移过程中两套生产者是否会并存

如果在灰度期存在 v1/v2 混跑，仅有 dual-read 不够，应该显式 dual-write 一段时间，否则会出现：

- 新写入数据只有 `agent`
- 老查询路径只盯 `department`
- 或反过来

这类问题最危险，因为不会立即报错，只会体现在“历史学习/预算统计/检索召回突然变差”。

### 2.3 `departments/` 不删除并不等于 rollback 真的可用

文档已经修复“过早删除 `departments/`”的问题，但 rollback 仍不稳，因为回滚不是只看目录是否存在，还依赖：

- root detection 全部改完
- 所有 v1 专用路径仍然完整
- 数据表字段在双态下都能被旧逻辑消费
- Qdrant payload 的双字段兼容真实可用
- 预算、dashboard、jobs 这些低频子系统没有暗中依赖新字段

换句话说，rollback 目前更像“理论上可切回”，不是“已被严格验证的运行级回退路径”。

### 2.4 热重载版本钉住只写了版本号，没有写清楚旧 registry 如何保活

文档说 `ComposedSpec` 和 task row 存 `registry_version`，这只解决“知道自己属于哪个版本”，没有解决“执行时还能拿到那个版本的 registry/FSM 定义”。

如果 `reload()` 只是原子替换一个全局 `RegistryState`：

- 新任务拿到新版本
- 旧任务只剩一个 `registry_version=17`
- 但内存里已经没有 version 17 的 registry snapshot

那版本号本身没有意义。  
要么需要版本化 registry 缓存并为 in-flight task 保留旧快照，要么就不能宣称 pinning 已解决热重载安全性。

### 2.5 低频路径的回归风险明显高于主路径

文档已经识别到大量影响半径，但低频路径仍最危险：

- periodic/proactive jobs
- token budget 与多预算系统
- Telegram/channel formatter
- shared knowledge / sync vectors
- evolution/risk loop
- eval/clawvard 路径

这些路径通常不会在“48 小时稳定运行”中被充分覆盖。  
如果 cutover 判据主要靠线上平稳和少量 eval，遗漏概率仍然很高。

### 2.6 旧系统调用约定非常简单，新系统调用约定显著变宽

当前代码中大量调用只传一个 `department` 或基于 `department` fallback。迁移后，正确行为依赖：

- agent
- intent
- profile
- authority_cap
- active_capabilities
- 有时还要 model / restrict_tools / reducer

这意味着只迁移字段名并不会自动得到正确行为。大量旧调用虽然“能跑”，但会 silently 退化成：

- 权限过大
- 模型过贵
- prompt 注入过多
- 自动链路过长

---

## 3. 提议中的代码/接口可能存在的 bug 或逻辑错误

### 3.1 `ComposedSpec.authority` 的定义与四级权限模型不一致

文档前面定义了四级：

- READ
- EXECUTE
- MUTATE
- APPROVE

但 `ComposedSpec` 示例里注释仍写成：

```python
authority: str  # READ / MUTATE / APPROVE
```

`EXECUTE` 被漏掉了。  
这看似小问题，实际会扩散到：

- schema 校验
- 序列化
- dashboard 展示
- semaphore tier
- 审计日志

这类字段定义不一致在迁移期非常容易演变成真正 bug。

### 3.2 `resolve_adhoc()` 的最小权限算法可能把可执行请求降成不可执行

伪代码里写的是：

```python
spec.authority = min(intent.authority_cap for intent in agents[0].intents.values())
```

问题在于它取的是“该 agent 所有 intent 的最低 authority_cap”，不是“本次 ad-hoc capability 组合对应 intent 的最低 authority_cap”。

结果可能是：

- 你 ad-hoc 请求 `[develop, test]`
- 覆盖到 `engineer`
- 但 `engineer` 某个只读 intent 把全局最小值拉到 READ
- 最终 ad-hoc spec 失去写权限，直接不可用

这是明显的逻辑错误，不是实现细节。

### 3.3 文档对 `active_caps` 与 `model_floor` 的适用范围仍不够自洽

正文说：

- tools/authority/model 从 `all_caps` 合成
- prompt/rubric 从 `active` 过滤

但示例代码又写：

```python
floor = max(c.model_floor for c in active_caps)
```

这会引出两个矛盾：

1. 非 active capability 仍能把 compose model 拉高，但不参与 floor；
2. 或者 floor 只看 active，导致某些能力的最低模型要求被绕开。

无论选择哪种，都需要明确、单一、可验证的规则。现在的写法还处于“作者自己大概懂”的状态。

### 3.4 Transition Rubric Override 段落与“FSM 纯字符串”结论存在残留冲突

文档中先给出一种嵌套 YAML：

```yaml
fact_layer: __self__
  rubric_override:
```

随后又声明 FSM 的 transition value 必须是纯字符串，并且 rubric override 已迁到 dispatcher `SPLIT_CONFIG`。

这意味着文档虽然在结论上修正了，但正文中仍保留过时接口示意。  
实现人员很容易照着旧片段落地出一版 schema，最终导致：

- registry loader 支持两套格式
- 或测试/样例与正式 schema 不一致

### 3.5 `intent can add restrict_tools list` 只出现在表格，没有完整契约

这个字段是为了修复“active_capabilities 不过滤 tools”的核心裂缝，但目前只存在于 resolution table 一行：

- 没有 schema
- 没有 merge 规则
- 没有验证规则
- 没有与 `resolve_tools()` 的交互说明
- 没有与 ad-hoc / scenario / subtask 的兼容说明

这意味着一个本来承载安全含义的字段，目前还是半个备注，不是完整接口。

### 3.6 热重载 + in-flight task pinning 只解决“识别版本”，未解决“执行取数”

这是本设计最容易被误判为“已解决”的问题。  
如果 Governor/FSM/Composer 在任务执行中会再次读取 registry，而 registry 只保留当前版本，那么 pinned task 实际仍会被新定义污染。

必须明确：

- `compose` 结果是否在创建 task 时完全物化
- FSM transition 是否也被物化
- specialization / prompts / rubrics 是否随 task 一起冻结

如果没有，这个版本钉住就是假的。

### 3.7 多 agent 调度的“覆盖匹配”缺少确定性契约

文档在不同位置给出过：

- greedy set-cover
- no coverage -> serial split
- scenario exact-set equality
- all READ -> parallel
- mixed authority -> sequential

但没有一个统一算法说明：

- 多个 agent 都能覆盖同一组 capability 时怎么选
- 最小 agent 数优先还是身份稳定优先
- 同权重冲突如何决策
- reducer 默认值是什么
- 调度顺序是否稳定

这会让调用方拿到一个“看似声明式、实则不可预测”的系统。

### 3.8 `compose(agent_key="engineer")` 仍暴露出一个危险的无 intent 快捷路径

文档把“via agent”写成正常路径：

```python
spec = composer.compose(agent_key="engineer")
```

但系统里很多关键约束都依赖 intent：

- `authority_cap`
- `active_capabilities`
- `profile`
- specialization

也就是说，不带 intent 的 compose 会默认给出“全能力合成”的 spec。  
如果这个 API 仍被大量直接调用，最终会稳定地产生过权 spec，而不是少数异常。

---

## 4. 消费者视角：从“调用 capability / agent 的代码”出发的体验问题

这里的“消费者”不是终端用户，而是仓库里调用这些能力的代码，例如 gateway、dispatcher、governor、subtask planner、group orchestration、periodic jobs。

### 4.1 新 API 入口太多，调用方先要决定“走哪扇门”

现在至少有这些入口概念：

- `compose(agent_key, intent)`
- `resolve_adhoc(capabilities)`
- `dispatch(capabilities=[...])`
- `run_parallel_scenario(name)`
- subtask 里声明 `capabilities`

对调用方而言，首先不是“怎么调用 agent”，而是“我该走哪个入口”。  
这会带来两个问题：

- 简单调用也要先理解架构分叉
- 不同入口得到的返回值和副作用可能不同

一个稳定系统应该优先让 80% 调用收敛到一个主入口，而不是让每个调用点先做模式选择。

### 4.2 调用方若只知道“我要 architect 做设计”，仍然很容易误用

理想中的调用应该是：

```python
dispatch(agent="architect", task="设计方案")
```

但在当前设计下，真正想得到“只读设计”行为，调用方至少要确保：

- agent = `architect`
- intent = `design_plan`
- 该 intent 正确配置了 `authority_cap=READ`
- active_capabilities 包含 `[plan, refactor]`

只要少一个条件，调用结果就可能退化为：

- MUTATE 权限
- opus + refactor 全量提示
- 可写路径开启

这对调用方并不友好，因为“安全的默认行为”没有体现在 API 表面。

### 4.3 调用方很难预测“调用一次 engineer，最终会得到几段执行链”

从文档流程看，一个单任务可能经历：

1. IntentGateway 路由
2. dispatcher enrichment
3. 可能的 phase 0.5 split
4. 主 agent 执行
5. Governor 基于 FSM 再创建 reviewer 任务
6. 结果经 reducer 合并

对消费者来说，最难的不是多一步，而是**链路的触发条件分散在多个层次**：

- 有的在 dispatcher
- 有的在 FSM
- 有的在 scenario
- 有的在 ad-hoc 匹配

这会让“我调用一次，为什么后台出现 3 个 task”变得很难解释，也很难编写稳定的集成测试。

### 4.4 返回类型不统一，调用方要处理 sum type

文档里 ad-hoc 可能返回：

- 单个 `ComposedSpec`
- `SuperstepPlan`

scenario 又是另一套路径，subtask 再是另一套声明方式。  
如果上层代码要统一接入，它就必须先做类型判断，再决定：

- 是直接执行
- 还是交给 governor
- 还是并行调度
- 还是等待 reducer

这类接口对调用方极不友好，因为它要求每个消费者都理解 orchestration 细节。

### 4.5 调用方无法从接口表面看出“最终权限/模型/工具为何如此”

调用者最需要的不是所有灵活性，而是可解释性。  
当前设计把真正决定结果的因素分散在：

- capability merge
- agent override
- intent override
- profile ceiling
- model floor
- restrict_tools
- scrutiny

这意味着调用方很难回答下面这些常见问题：

- 为什么这次是 `opus` 不是 `sonnet`
- 为什么这次虽然是 reviewer prompt，却还能用某些工具
- 为什么 architect 进了 READ tier
- 为什么 ad-hoc 被强制串行

文档里提到要加 `_trace`，这恰恰说明当前接口缺少“人类可读的决策面”。

### 4.6 从当前代码迁移过来，消费者会明显感到“原来只需要 department，现在要带一整包上下文”

当前代码的主调用契约非常简单，例如：

- `TaskIntent.department`
- `resolve_route(intent, department)`
- `spec["department"]`

而新世界里，如果调用方想避免隐式 fallback，就会倾向于显式传：

- agent
- intent
- profile
- authority_cap
- active_capabilities
- capabilities
- depends_on
- reducer

这会扩大上层业务代码的负担。  
如果设计者希望“调用方只填 agent+intent，其余靠 registry 解出”，那就应该把这个最简主路径定义得更强，不该保留太多可选侧门。

---

## 重点结论

### 建议视为 P0 的问题

1. **热重载版本钉住没有闭环**  
只记录 `registry_version` 不够，必须定义旧版本 registry/FSM/prompt/rubric 如何在 in-flight task 生命周期内持续可取。

2. **`resolve_adhoc()` 的权限计算逻辑不对**  
按 agent 全量 intents 取最小 `authority_cap` 会把本应可执行/可变更的 ad-hoc 请求错误降权。

3. **无 intent 的 `compose(agent_key=...)` 仍是危险主入口**  
如果保留，必须明确它只能用于内部极少数场景；对外主入口必须要求 intent，或者默认绑定 agent 的 safe default intent。

### 建议视为 P1 的问题

1. `active_capabilities` 与 tools/model/authority 分离后，系统语义仍然别扭，`restrict_tools` 只是补丁，不是完整闭环。
2. Dispatcher Phase 0.5 职责过重，后续极容易再次长成不可维护的“大调度器”。
3. 整体迁移虽然写成 feature-flagged，但执行面仍接近大爆炸，尤其是 dual-write、低频路径和 rollback 验证不足。
4. 面向调用方的 API 入口过多、返回类型不统一、行为触发点分散，消费者体验明显变差。

---

## 建议的收敛方向

如果目标是让 v1 可落地且可维护，我建议优先做以下收敛：

1. **强制主路径只有一种调用方式**  
对外统一为 `dispatch(agent, intent, task)`；ad-hoc 和 scenario 都降为内部适配层，不暴露为并列一等入口。

2. **去掉无 intent compose 的常规地位**  
要求所有 agent 执行都绑定 intent；没有 intent 就落到 agent default intent，而不是全量 capability 合成。

3. **把 model/tool/authority 的解释规则再砍一层**  
如果 `active_capabilities` 不参与 tools/authority/model，就不要再用它承载“看起来像能力选择”的语义；要么改名，要么让它真正参与一个可预测的子集。

4. **把 hot reload pinning 从“版本号”升级为“快照生命周期”设计**  
否则这部分只是看起来严谨。

5. **在迁移计划里显式加入 dual-write 和低频场景回放清单**  
不然“48 小时稳定”不足以支撑 cutover。

---

## 最终评价

这份设计的方向是对的，但它还没有达到“可以放心进入实现”的简洁度。  
当前最大问题不是少一个字段或少一条迁移脚本，而是系统同时试图解决太多问题，导致每一层都在为另一层打补丁。

如果按当前形态直接实现，最可能出现的结果不是“完全失败”，而是：

- 主路径勉强可用
- 低频路径持续漏水
- 调用方误用率高
- 热重载、ad-hoc、迁移兼容这些复杂路径长期处于半可信状态

这类系统最危险，因为它会在看起来“设计很完整”的情况下，把复杂度债务转移到实现阶段和后续维护阶段。
