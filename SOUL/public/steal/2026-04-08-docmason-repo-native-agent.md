# R45b — DocMason Steal Report

**Source**: https://github.com/JetXu-LLM/DocMason | **Stars**: 71 | **License**: Apache-2.0
**Date**: 2026-04-08 | **Category**: Framework (Repo-Native Agent App)

## TL;DR

"The repo is the app. Codex is the runtime." — 零后端服务的文件系统驱动 agent 应用。核心值不在文档研究本身，而在它实现了一套完整的**文件系统级分布式协调 + 证据溯源 + 合约验证**的 agent 治理架构。这是目前见到的最成熟的 repo-native agent 治理实现。

## Architecture Overview

```
Layer 4: Skills (13 canonical + operator)
  │  SKILL.md + workflow.json sidecar
  │  结构化路由 → 确定性意图匹配
  │
Layer 3: Routing & Truth Boundary
  │  routing.py: 语义分析归一化 + 保守回退
  │  truth_boundary.py: 源证据范围策略 + 段落级溯源
  │  admissibility.py: 提交前合规门
  │
Layer 2: Control Plane & Coordination
  │  control_plane.py: Shared Job 状态机 (running → awaiting-confirmation → completed/blocked)
  │  coordination.py: mkdir 原子性文件系统锁 + 过期检测
  │  projections.py: 脏标记 + 后台 worker 刷新派生视图
  │
Layer 1: Contracts & Hooks
  │  contracts.py: 运行时合约验证 (answer_state × support_basis)
  │  hooks.py: Claude Code hook → JSONL interaction mirror
  │
Layer 0: File System (repo = database = API)
    project.py: WorkspacePaths, read_json, write_json, append_jsonl
```

## Steal Sheet

### P0 — Must Steal (4 patterns)

#### 1. Shared Job Control Plane — 文件系统级分布式任务协调

**What**: 基于文件系统的幂等任务创建 + 去重 + stale 检测 + 状态机流转。

**How** (核心机制):
```python
# ensure_shared_job(): 幂等 — 同 input_signature 返回现有 job，不同才创建
def ensure_shared_job(paths, *, job_key, input_signature, owner, ...):
    with workspace_lease(paths, f"shared-job:{job_key}"):
        index = load_shared_jobs_index(paths)
        active_job_id = index["active_by_key"].get(job_key)
        if active_job_id:
            manifest = load_shared_job(paths, active_job_id)
            if manifest.get("input_signature") == input_signature:
                # 幂等命中 — 同签名任务已存在
                if _shared_job_stale(manifest):
                    # 接管 stale 任务的 owner
                    manifest["owner"] = owner
                    manifest["attempt_count"] += 1
                return {"manifest": manifest, "created": False, "caller_role": "waiter"}
        # 创建新任务
        manifest = _create_shared_job(paths, ...)
        return {"manifest": manifest, "created": True, "caller_role": "owner"}
```

**Why it's good**:
- `input_signature` 做内容哈希去重 → 多个 agent 同时请求同一任务时只执行一次
- `_owner_process_is_active()` 用 `os.kill(pid, 0)` 检测进程存活 → 自动回收死掉的 owner
- 状态机 `running → awaiting-confirmation → completed/blocked` → 需要用户确认的大操作有显式等待点
- `caller_role` 区分 owner/waiter/awaiting-confirmation → 调用方知道自己该等还是该干活

**Knowledge categories**: Pitfall memory (stale owner 检测), Judgment heuristics (幂等签名去重), Unique behavioral patterns (文件系统即数据库)

**Triple validation**:
- ✅ Cross-domain: 类似 Kubernetes Job controller 的幂等语义；Celery 的 task dedup
- ✅ Generative: 给定"两个 agent 同时发起 KB sync"→ 预测行为：第二个成为 waiter
- ✅ Exclusive: 用 mkdir 原子性 + JSON manifest + PID 存活检测的组合是独特的

| Capability | DocMason | Orchestrator | Gap | Action |
|-----------|---------|-------------|-----|--------|
| 任务幂等创建 | input_signature hash + job_key | 无（sub-agent 独立运行） | Large | Steal |
| 调用方角色区分 | owner/waiter/confirmation | 无 | Large | Steal |
| Stale owner 回收 | PID + run_state 双重检测 | 无 | Large | Steal |
| 状态机 | 5 states + journal | 无 | Large | Steal |

**Adaptation**: 新建 `src/governance/shared_jobs.py`。当前 sub-agent 派单没有共享任务去重——两个 agent 可能同时做同一件事。

---

#### 2. 文件系统互斥锁 — mkdir 原子性 + stale 检测

**What**: context manager 风格的文件系统锁，跨平台，自带超时和过期清理。

**How**:
```python
@contextmanager
def workspace_lease(paths, resource, *, timeout_seconds=10.0,
                    poll_interval_seconds=0.05, stale_after_seconds=600.0):
    payload = {"resource": resource, "owner": str(uuid.uuid4()), "created_at": _utc_now()}
    target = lease_dir(paths, resource)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            target.mkdir(parents=False, exist_ok=False)  # OS-level atomic
        except FileExistsError:
            if target.exists() and not target.is_dir():
                target.unlink()  # 非目录 → 清除异常
                continue
            if _stale_lease(target, stale_after_seconds=stale_after_seconds):
                shutil.rmtree(target, ignore_errors=True)  # 过期 → 强制回收
                continue
            if time.monotonic() >= deadline:
                raise LeaseConflictError(...)
            time.sleep(poll_interval_seconds)
            continue
        # 写 lease.json 记录 owner
        (target / "lease.json").write_text(json.dumps(payload))
        break
    try:
        yield payload
    finally:
        lease_info = read_json(target / "lease.json")
        if lease_info.get("owner") == payload["owner"]:  # 只释放自己的锁
            shutil.rmtree(target, ignore_errors=True)
```

**Why it's good**:
- `mkdir(exist_ok=False)` 是 POSIX/Windows 都保证原子性的操作 — 比 fcntl.flock 更跨平台
- `_stale_lease()` 双重判定：先看 lease.json 内容，没有时看目录 mtime
- 释放时验证 owner 一致 → 防止两个进程互相释放
- `_FRESH_LEASE_WRITE_GRACE_SECONDS = 1.0` — 刚创建的目录还没来得及写 lease.json 时的宽限期

**Knowledge categories**: Pitfall memory (Windows 上 fcntl 不可用), Hidden context (1s 宽限期的存在说明有过"mkdir 成功但还没写 JSON 就被判 stale"的 bug)

**Triple validation**:
- ✅ Cross-domain: Redis SETNX, ZooKeeper ephemeral node
- ✅ Generative: 预测"进程 crash 后锁怎么回收" → stale_after_seconds
- ✅ Exclusive: mkdir + lease.json + owner 验证 + 宽限期的组合

| Capability | DocMason | Orchestrator | Gap | Action |
|-----------|---------|-------------|-----|--------|
| 跨平台互斥 | mkdir atomic | 无锁机制 | Large | Steal |
| Stale 回收 | 时间 + JSON | 无 | Large | Steal |
| Owner 安全释放 | 验证 owner 一致 | N/A | Large | Steal |

**Adaptation**: 提取为 `src/utils/fs_lock.py`，供 shared_jobs、projection worker、Docker 状态等使用。

---

#### 3. Workflow Metadata Sidecar — 结构化 skill 路由

**What**: 每个 skill 旁放 `workflow.json`，声明 entry_intents、execution_hints、handoff 协议。Python 做严格 schema 验证。

**How**:
```json
{
  "schema_version": 1,
  "workflow_id": "grounded-answer",
  "category": "answer",
  "entry_intents": ["answer a grounded question", "respond from the published knowledge base"],
  "required_capabilities": ["local file access", "shell or command execution"],
  "defaults": {"default_target": "current", "default_mode": "answer-question"},
  "execution_hints": {
    "mutability": "read-only",
    "parallelism": "read-only-safe",
    "background_commands": ["docmason retrieve \"<query>\" --json"],
    "must_return_to_main_agent": true
  },
  "handoff": {
    "completion_signal": "Return the final answer text, answer state, and support boundary.",
    "artifacts": ["runtime/logs/query-sessions/<session_id>.json"],
    "follow_up": ["provenance-trace", "runtime-log-review"]
  }
}
```

Python 端 `WorkflowMetadata` dataclass 做严格验证：
```python
@dataclass(frozen=True)
class WorkflowMetadata:
    workflow_id: str
    category: str  # foundation | adapter | knowledge-base | evidence-access | answer | review
    entry_intents: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    execution_hints: dict[str, Any]  # mutability, parallelism, background_commands
    handoff: dict[str, Any]          # completion_signal, artifacts, follow_up
    user_entry: dict[str, Any] | None  # 用户可见路由入口
```

**Why it's good**:
- `mutability: read-only | workspace-write` → 调度器知道哪些 skill 可以安全并行
- `parallelism: none | read-only-safe | per-source-safe` → 三级并行安全性声明
- `must_return_to_main_agent: true` → 显式声明 sub-agent 必须归还控制权
- `handoff.artifacts` + `handoff.follow_up` → 后续 skill 知道上游产出了什么

**Knowledge categories**: Judgment heuristics (mutability 分级), Unique behavioral patterns (机器可读的 skill 合约)

**Triple validation**:
- ✅ Cross-domain: OpenAPI spec for skills; Kubernetes Pod spec
- ✅ Generative: "这个 skill 能并行吗？" → 查 parallelism 字段即可判定
- ⚠️ Exclusive: 半通过 — 概念不新（元数据），但 parallelism + handoff 组合是独特的

| Capability | DocMason | Orchestrator | Gap | Action |
|-----------|---------|-------------|-----|--------|
| Skill 元数据 | workflow.json + Python 验证 | SKILL.md frontmatter（纯文本） | Medium | Steal |
| 并行安全声明 | 三级 parallelism | 无 | Large | Steal |
| Handoff 协议 | 显式 artifacts + follow_up | 无 | Large | Steal |
| Mutability 标记 | read-only / workspace-write | 无 | Large | Steal |

**Adaptation**: 为每个 `.claude/skills/*/SKILL.md` 添加 `workflow.json` sidecar。在 `skill_routing.md` 中引用 parallelism 字段做调度决策。

---

#### 4. Truth Boundary 溯源守卫 — 段落级证据审计

**What**: 每个回答的每个段落追踪证据来源，标注 grounded/partially-grounded/unresolved/abstained，检测违规（路径泄露、来源缺失、比较覆盖不全）。

**How**:
```python
# 1. 根据问题语义推断证据范围策略
def build_source_scope_policy(*, question, question_class, reference_resolution):
    # 四种范围模式
    scope_mode = "global"  # 默认
    if compare_scope:
        scope_mode = "compare"  # 比较题：要求 ≥2 个来源
    elif hard_boundary or explicit_single_source:
        scope_mode = "source-scoped-hard"  # 指定来源（严格）
    elif target_source_id and source_narrowing_allowed:
        scope_mode = "source-scoped-soft"  # 推断来源（宽松）

# 2. 检测问题码
def trace_issue_codes(*, answer_state, canonical_support_summary, ...):
    issue_codes = []
    if published_artifacts_sufficient is False:
        issue_codes.append("published-artifacts-gap")
    if scope_mode in SOURCE_SCOPED_MODES and not scope_satisfied:
        issue_codes.append("source-scope-missing-target-support")
    if scope_mode == "compare" and not scope_satisfied:
        issue_codes.append("compare-source-coverage-missing")
    # answer_state 说 grounded 但段落有 unresolved → 自相矛盾
    if answer_state == "grounded" and unresolved_count > 0:
        issue_codes.append("trace-answer-state-mismatch")

# 3. 防泄露：检测回答中的绝对路径
def answer_mentions_illegal_machine_path(answer_text):
    for match in ABSOLUTE_PATH_PATTERN.finditer(answer_text):
        if not prefix.endswith("http://") and Path(candidate).is_absolute():
            return True  # 泄露了本机路径
```

**Why it's good**:
- 不只是"有没有证据"的布尔判断 → 四级 scope_mode × 四级 grounding_status 的矩阵
- `trace_issue_codes()` 输出具体问题码 → 机器可读的质量报告
- `answer_mentions_illegal_machine_path()` → 防止 agent 在回答中泄露本机绝对路径
- 比我们的 evidence tier (verbatim/artifact/impression) 更精细 — 我们是记忆层面的，它是回答层面的

**Knowledge categories**: Failure memory (路径泄露是真实生产 bug), Judgment heuristics (scope_mode 四级分类), Unique behavioral patterns (段落级溯源)

**Triple validation**:
- ✅ Cross-domain: RAG 系统的 citation grounding; 学术论文引用验证
- ✅ Generative: "用户问 compare A vs B，只有 A 的证据" → 预测 issue_code = compare-source-coverage-missing
- ✅ Exclusive: scope_mode + segment-level grounding + issue_codes 三层组合

| Capability | DocMason | Orchestrator | Gap | Action |
|-----------|---------|-------------|-----|--------|
| 回答级证据分级 | 4 states + scope_mode | evidence tier（记忆层） | Medium | Steal |
| 段落级溯源 | segment_traces | 无 | Large | Steal |
| 问题码检测 | 7+ issue codes | 无 | Large | Steal |
| 路径泄露防护 | regex + 排除 http | 无 | Medium | Steal |

**Adaptation**: 在分析模块（daily report, profile analysis）的输出中加入 grounding_status。在 verification-gate 中检查 trace_issue_codes。

---

### P1 — Worth Doing (4 patterns)

| Pattern | Mechanism | Adaptation | Effort |
|---------|-----------|------------|--------|
| **Commit Contract** | `validate_commit_contract()` 强制 answer_state + support_basis 非空 + 外部来源必须有 manifest_path | 在 verification-gate 的 evidence chain 中加 commit contract check | ~2h |
| **Projection Refresh Worker** | 脏标记 + change_sequence + target_digest 哈希 → 后台 subprocess worker 用 `start_new_session=True` 刷新派生视图 | Dashboard 的统计视图可以用类似模式后台刷新 | ~4h |
| **Interaction Ingest via Hooks** | 5 种 Claude Code hook 事件 → JSONL 按 session_id 分文件 → 完整交互镜像 | 扩展 audit.sh 记录 tool_input + tool_response | ~2h |
| **Materiality Classification** | `classify_sync_materiality()` 按 changed_total(≥12)、changed_ratio(≥15%)、destructive_total(≥3) 判断"重大变更" | Gate Functions 中加变更规模评估 | ~2h |

### P2 — Reference Only (3 patterns)

| Pattern | Mechanism | Why ref-only |
|---------|-----------|-------------|
| **AGENTS.md 三层合约** | AGENTS.md（顶层路由）→ SKILL.md（流程）→ workflow.json（机器可读）| 我们已有 CLAUDE.md → SKILL.md，加 workflow.json 即可（已在 P0-3） |
| **语义路由哲学** | "routing 应来自 agent 推理，不是关键词表" — routing.py 只做归一化和保守回退 | 设计理念一致，无实施差距 |
| **Sample Corpus + Operator Eval** | 内置样例语料 + 结构化评估框架 | 我们有 Clawvard 考试体系，功能覆盖 |

## Gaps Identified (Six Dimensions)

| Dimension | DocMason | Orchestrator | Gap |
|-----------|---------|-------------|-----|
| **Security / Governance** | 路径泄露检测、source_scope 硬边界、commit contract | Gate Functions + guard.sh | 我们缺回答级泄露检测 |
| **Memory / Learning** | 6 种 memory_kind（constraint/preference/clarification/operator-intent/fact/working-note）+ durability + uncertainty | evidence tier (3 级) | 我们的记忆分类更粗 |
| **Execution / Orchestration** | Shared Job 状态机 + 文件系统锁 | sub-agent 独立运行 | **最大差距** — 无共享状态 |
| **Context / Budget** | 无显式 token 预算 | boot.md 编译器 | 我们更强 |
| **Failure / Recovery** | stale lease 回收、owner PID 检测、block 状态 | 无任务级故障恢复 | 显著差距 |
| **Quality / Review** | trace_issue_codes + commit contract + admissibility | verification-gate | 我们有但粒度更粗 |

## Adjacent Discoveries

1. **`_FRESH_LEASE_WRITE_GRACE_SECONDS = 1.0`** — 这个常量暴露了一个真实踩坑：mkdir 成功后还没写 lease.json 就被另一个进程判定为 stale。1 秒宽限期是经验值，不是理论值。我们实现文件锁时必须考虑这个时间窗口。

2. **`start_new_session=True`** — projection worker 用这个参数确保后台进程独立于父进程的会话。Windows 上对应 `CREATE_NEW_PROCESS_GROUP`，和 `subprocess.DETACHED_PROCESS` 不同。我们 Docker 环境可能不需要，但在本地模式下有用。

3. **`normalize_confirmation_reply()` 支持中文** — `"\u4e00" <= character <= "\u9fff"` 过滤条件保留了中文字符，说明作者考虑了中文用户。我们的确认流程也应该支持中文输入。

4. **`_stable_json_digest()`** — `json.dumps(sort_keys=True, separators=(",", ":"))` 做确定性序列化后再 SHA256。这比直接比较 dict 更可靠（dict 比较会被 float 精度、None vs missing 等干扰）。

## Meta Insights

1. **文件系统是被低估的分布式协调原语**：DocMason 用 mkdir 原子性 + JSON manifest 实现了一个轻量版的 distributed lock + job queue，没有引入 Redis/RabbitMQ/etcd。在 agent 场景下这很合理——任务粒度粗（分钟级不是毫秒级），并发度低（个位数不是千级），文件系统的性能绰绰有余。我们的 sub-agent 派单目前是"fire and forget"，缺少共享状态层。

2. **"Zero Backend" 不是技术限制，是架构决策**：DocMason 选择文件系统而非数据库/API，不是因为做不到后端，而是因为 repo-native 意味着用户可以 `git diff` 看到所有状态变化。这和我们 SOUL 系统的理念一致——"repo = 身体"。区别是他们把执行状态也放进了文件系统，而我们用 Docker + SQLite。各有取舍：他们的可审计性更强，我们的并发安全性更好。

3. **Commit Contract 是 Verification Gate 的结构化升级**：我们的 verification-gate 是五步证据链（Identify → Execute → Read → Confirm → Declare），本质上依赖 prompt compliance。DocMason 的 `validate_commit_contract()` 是代码级强制——answer_state 和 support_basis 非空才能提交。**硬约束 > 软约束**的一贯教训。

4. **Truth Boundary 填补了我们的"回答层"空白**：我们的 evidence tier 管的是记忆（"这条信息可信度如何"），DocMason 的 truth boundary 管的是回答（"这个段落有没有证据支撑"）。两个层面不矛盾，可以叠加：记忆写入时用 evidence tier 过滤，回答生成时用 truth boundary 审计。

5. **Workflow Metadata 是 skill routing 的"声明式革命"**：我们的 skill routing 靠 description 字段做自然语言匹配（"这个 skill 看起来适合"），DocMason 用 workflow.json 做确定性匹配（"这个 skill 的 entry_intents 包含 X，mutability 是 read-only，可以并行"）。从"猜测式路由"到"声明式路由"的进化。
