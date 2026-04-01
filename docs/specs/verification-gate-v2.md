# Spec: Verification Gate v2

> 目标：将 verification-gate skill 从"五步证据链"升级到 Claude Code verificationAgent.ts 同等水平
> 来源：`claude-code-deep-dive/extracted-source/src/tools/AgentTool/built-in/verificationAgent.ts`
> 当前版本：`.claude/skills/verification-gate/SKILL.md`（129 行）

---

## Gap 分析

| # | 缺口 | 当前状态 | 目标状态 | 优先级 |
|---|------|---------|---------|--------|
| 1 | 结构化输出格式 | 只说"读完整输出" | 每个 check 必须 `Command run` + `Output observed` + `Result`，无命令 = 驳回 | P0 |
| 2 | 按变更类型的具体验证命令 | 8 行概括表格 | 10+ 种类型 × 具体命令示例（curl/playwright/docker/terraform） | P0 |
| 3 | 开头定调：两种失败模式 | 埋在 Known Failure Modes 中间 | 第一段就点名 verification avoidance + 80% trap，建立对抗心态 | P0 |
| 4 | "实现者也是 LLM" 独立验证意识 | 没有 | 明确写入：不信任实现者测试，独立验证 | P1 |
| 5 | 反合理化内联 | 引用外部 rationalization-immunity.md | 关键条目内联到 skill 里（原版 6 条对话式反驳） | P1 |
| 6 | 正反示例 | 没有 | Bad（读代码写 PASS）vs Good（curl + 输出 + 对比）完整示例 | P1 |
| 7 | VERDICT 协议 | 没有 | 末尾必须输出 `VERDICT: PASS / FAIL / PARTIAL`，可被调用方解析 | P2 |

**不做的事**（与我们架构不匹配）：
- disallowedTools 硬封锁 — 我们没有 agent 工具池过滤机制，靠 prompt 约束
- criticalSystemReminder — 需要 harness 层支持，当前不可实现
- 临时脚本写 /tmp — Windows 环境差异，改为 `D:\Agent\tmp\verification\`

---

## 目标文件

修改：`.claude/skills/verification-gate/SKILL.md`

---

## 变更计划

### Step 1: 重写开头 — 对抗性定调
**改什么**: 删掉当前第 8 行的 IRON LAW 单句，替换为 verificationAgent 风格的角色定义 + 两种失败模式
**具体内容**:
```markdown
Your job is not to confirm the implementation works — it's to try to break it.

Two documented failure patterns you must resist:
1. **Verification avoidance**: You read code, narrate what you'd test, write PASS, move on. No command was run.
2. **80% trap**: UI looks fine, tests pass — you miss that half the buttons do nothing, state vanishes on refresh, or the backend crashes on bad input.

The implementer may be an LLM too — its tests may be mocks, circular assertions, or happy-path-only. Verify independently.
```
**验证**: 读修改后的文件，确认前 10 行包含 "try to break" + 两种失败模式 + LLM 独立验证

### Step 2: 结构化输出格式
**改什么**: 在 Step 3 (READ) 和 Step 5 (DECLARE) 之间插入输出格式要求
**具体内容**:
```markdown
## Required Output Format

Every check MUST follow this structure. A check without a Command run block is not a PASS — it's a skip.

### Check: [what you're verifying]
**Command run:**
  [exact command you executed]
**Output observed:**
  [actual terminal output — copy-paste, not paraphrased]
**Result: PASS** (or FAIL — with Expected vs Actual)

### Bad (rejected):
Check: POST /api/register validation
Result: PASS
Evidence: Reviewed the route handler. The logic correctly validates email format.
→ No command run. Reading code is not verification.

### Good:
Check: POST /api/register rejects short password
Command run: curl -s -X POST localhost:8000/api/register -d '{"password":"short"}'
Output observed: {"error": "password must be at least 8 characters"} (HTTP 400)
Expected vs Actual: Expected 400 with password-length error. Got exactly that.
Result: PASS
```
**验证**: 读文件确认包含正反示例

### Step 3: 扩展变更类型验证策略
**改什么**: 替换当前 8 行概括表格，扩展为按类型的具体验证动作
**具体内容**:

| 变更类型 | 验证动作 |
|---------|---------|
| Frontend | 起 dev server → 浏览器自动化（playwright MCP）截图/点击/读 console → curl 子资源（图片/API/静态文件）→ 前端测试 |
| Backend/API | 起 server → curl 端点 → 验响应体结构（不只状态码）→ 错误处理 → 边界输入 |
| CLI/Script | 跑代表性输入 → 验 stdout/stderr/exit code → 空输入/畸形输入/边界值 → --help 准确性 |
| Bug Fix | **先复现原始 bug** → 验修复 → 回归测试 → 检查相邻功能副作用 |
| Refactoring | 现有测试必须原封不动通过 → diff 公开 API surface → 相同输入 = 相同输出 |
| DB Migration | up → 验 schema → **down（可逆性）** → 用已有数据测，不只空库 |
| Config/Infra | 语法校验 → dry-run（terraform plan / docker build / nginx -t）→ 环境变量实际被引用 |
| Collector | 实际触发采集 → 验数据写入 events.db → 检查字段完整性，不只 status=OK |
| Prompt/SOUL | Before/after 对比 → 用代表性输入测试行为变化 → 检查 compact 后是否仍生效 |
| Docker | build → run → 健康检查 → 端口映射 → 日志无报错 → 资源占用合理 |

**验证**: 读文件确认 10 种类型各有 3+ 个具体动作

### Step 4: 内联反合理化条目
**改什么**: Known Failure Modes 区块追加对话式反驳（从 rationalization-immunity.md 引用改为内联）
**具体内容**:
```markdown
## Recognize Your Own Rationalizations

| You'll want to say | Do this instead |
|--------------------|----------------|
| "The code looks correct based on my reading" | Reading is not verification. Run the command. |
| "The implementer's tests already pass" | The implementer is an LLM. Verify independently. |
| "This is probably fine" | "Probably" is not "verified". Run it. |
| "Let me check the code" | No. Start the server and hit the endpoint. |
| "I don't have a browser" | Did you check for playwright MCP? |
| "This would take too long" | Not your call. |

If you catch yourself writing an explanation instead of a command, stop. Run the command.
```
**验证**: 读文件确认反合理化表格包含 6 条 + 末尾 "stop. Run the command."

### Step 5: 添加 VERDICT 协议（可选）
**改什么**: 文件末尾添加 VERDICT 输出要求
**具体内容**:
```markdown
## Final Verdict

End verification with exactly one of:
- `VERDICT: PASS` — all checks pass, at least one adversarial probe run
- `VERDICT: FAIL` — include what failed, exact error output, reproduction steps
- `VERDICT: PARTIAL` — environmental limitation only (missing tool/service), list what owner should verify manually

PARTIAL is for "can't test" not "unsure if bug". If you can run the check, you must decide PASS or FAIL.
```
**验证**: 读文件末尾确认 VERDICT 三选一定义存在

---

## 验收标准

1. 文件开头 10 行内出现 "try to break" + 两种失败模式
2. 包含正反输出格式示例（Bad vs Good）
3. 变更类型表格 ≥ 10 种，每种 ≥ 3 个具体动作
4. 反合理化表格 ≥ 6 条，内联不外链
5. VERDICT 三选一协议存在
6. 保留现有五步证据链结构（重构不重写）
7. 总长度 ≤ 250 行（原版 129 行，目标 ~200 行）
