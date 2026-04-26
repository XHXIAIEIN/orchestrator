# Memory Axioms Gate

四条记忆写入公理。任何对 `SOUL/`、`.claude/memory/`、或全局 `~/.claude/projects/.../memory/` 的写入操作，**先过这道闸**。任一公理失败 → 中止写入 + 解释失败的公理。

来源：R82 GenericAgent steal — 引擎级记忆治理，不能仅靠 prompt 约束。

---

## ① Action-Verified Only — 没执行过，不写入

**No Execution, No Memory**：信息必须有对应的 commit hash、命令输出、或可复现的事实证据，才能写入 L1（短期）或 L2（项目级）记忆。

**触发条件**：
- 写入文件路径包含 `SOUL/`、`.claude/memory/`、`memory/`
- 写入内容包含具体的事实声明（"X 已修复"、"Y 配置为 Z"、"测试通过"）

**违反样例**：
- ❌ "I think the bug is fixed" — 没跑测试
- ❌ "Decision: use Redis for caching" — 没有 commit / ADR
- ✅ "Fixed in commit `abc1234`: regex now matches `\\d{5,}`. Test output: `pytest tests/test_regex.py::test_volatile_match PASSED`"

---

## ② Sanctity of Verified Data — 已验证的不可丢

**GC 时不得丢弃** `evidence: verbatim` 或 `evidence: artifact` 的条目。低置信度（`evidence: impression`）才是 GC 候选。

**触发条件**：
- 任何记忆文件清理 / 压缩 / 归档操作
- `compress_history`、`memory_gc`、`archive_old`

**违反样例**：
- ❌ 按时间戳一刀切删除 30 天前的记忆 — 会丢掉 verbatim 用户原话
- ✅ 按 `evidence` tier 分级 GC：先删 `impression`，再考虑老的 `artifact`，永不删 `verbatim`

---

## ③ No Volatile State — 不写易腐数据

**禁止**在记忆文件中写入：
- 进程 ID（PID）、随机端口号、临时路径（`/tmp/...`、`C:\Users\...\Temp\...`）
- 时间戳（`2026-04-27 03:14:07`）—— 除非作为事件标签且语义稳定
- session ID（`cli-1745719847-12345`）
- localhost / 内网 IP + 端口（`localhost:5432`、`127.0.0.1:8080`）
- 容器 ID、PID、随机生成的 UUID（除非是稳定标识符）

**触发条件**：写入内容匹配易腐 pattern。详见 `.claude/skills/memory-axioms/constraints/no-volatile-state.md`。

**违反样例**：
- ❌ "Current orchestrator container: PID 47291, port 5432" — 重启即失效
- ✅ "Orchestrator container 通过 docker-compose 启动，端口由 `docker-compose.yml` 定义"

---

## ④ Minimum Sufficient Pointer — 只记最小召回信息

只记录召回所需的最小信息。**文件名+行号优于复制整段代码**；**commit hash 优于完整 diff**。

**理由**：
- 大段复制会膨胀 context，召回时再 Read 一次即可
- 代码会变，但 commit hash 永久稳定
- 召回 pointer 即可重建上下文，不需要重述细节

**触发条件**：写入内容包含 >30 行代码片段、或完整 diff、或可索引的文件全文。

**违反样例**：
- ❌ 把整个 `src/storage/events_db.py:140-280` 函数体复制进 memory
- ✅ "EventsDB 记忆同步逻辑：`src/storage/events_db.py:sync_memory_dir` (commit `4cb3b14`)"

---

## Gate 流程

```
write_request → memory_axioms_gate
  ├── ① action-verified? → 没证据 → ABORT, 报告缺失证据
  ├── ② sanctity check (if GC)? → 涉及 verbatim/artifact → ABORT, 改 GC 策略
  ├── ③ volatile-state regex? → 命中 → ABORT, 报告匹配位置
  └── ④ minimum-pointer check? → 大段复制 → ABORT, 改写为 pointer
       └── 全部通过 → PROCEED
```

---

## 失败时的产出

不能默默放过。Gate 失败时输出格式：

```
[memory-axioms] Write rejected.
  Axiom failed: ③ No Volatile State
  Match: "PID 47291" at line 12
  Fix: Replace with stable identifier (container name / service role).
```

让 agent 看到具体哪一条失败、具体在哪、具体怎么改。
