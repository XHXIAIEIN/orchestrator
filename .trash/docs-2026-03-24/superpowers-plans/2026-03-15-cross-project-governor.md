# Governor 跨项目调度能力 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Governor 能派 sub-agent 到任意 git 项目目录执行任务，而不是只在 /orchestrator 里干活。

**Architecture:** 新增项目注册表（自动扫描 /git-repos + 手动覆盖），改 docker-compose 把 /git-repos 从 ro 改 rw，修改 Governor/DebtScanner/InsightEngine 支持 project 和 cwd 字段。sub-agent 通过 `claude -p "task" --output-format json` 在目标项目 cwd 下执行，自动读取目标项目的 CLAUDE.md。

**Tech Stack:** Python 3, SQLite, Docker Compose, Claude CLI

---

## Chunk 1: 基础设施

### Task 1: docker-compose.yml — /git-repos 改为 rw

**Files:**
- Modify: `docker-compose.yml:37-40`

- [ ] **Step 1: 修改挂载权限**

```yaml
      # Git repos (read-write for cross-project task execution)
      - type: bind
        source: ${GIT_ROOT:-~/Documents/GitHub}
        target: /git-repos
```

去掉 `read_only: true`。

- [ ] **Step 2: 验证**

Run: `docker compose config | grep -A2 git-repos`
Expected: 无 `read_only` 字段

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: make /git-repos writable for cross-project task execution"
```

---

### Task 2: 项目注册表 src/project_registry.py

**Files:**
- Create: `src/project_registry.py`

- [ ] **Step 1: 创建注册表模块**

```python
"""
项目注册表 — 管理 Orchestrator 可调度的项目清单。

自动扫描 /git-repos 下的 git 仓库，支持手动配置覆盖。
提供 project_name → container_path 映射，供 Governor 路由任务。
"""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

GIT_REPOS_ROOT = os.environ.get("GIT_REPOS_ROOT", "/git-repos")
ORCHESTRATOR_ROOT = os.environ.get("ORCHESTRATOR_ROOT", "/orchestrator")
REGISTRY_FILE = Path(ORCHESTRATOR_ROOT) / "project_registry.json"

# Claude projects 目录名 → 项目名的映射规则
# e.g. "D--Users-Administrator-Documents-GitHub-Construct3-RAG" → "Construct3-RAG"
def _claude_dir_to_project(dirname: str) -> str:
    """从 Claude projects 目录名提取项目名。"""
    # 去掉盘符前缀，取最后一段
    parts = dirname.replace("--", "/").split("/")
    # 找到 GitHub 之后的部分
    for i, p in enumerate(parts):
        if p.lower() == "github":
            rest = parts[i+1:]
            if rest:
                return "-".join(rest)
    # fallback: 取最后一段
    return parts[-1] if parts else dirname


def scan_repos() -> dict[str, dict]:
    """扫描 /git-repos 下所有目录，返回 {project_name: {path, has_claude_md}}。"""
    root = Path(GIT_REPOS_ROOT)
    if not root.exists():
        log.warning(f"ProjectRegistry: {GIT_REPOS_ROOT} not found")
        return {}

    projects = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        # 检查是否是 git 仓库（有 .git 目录或文件）
        is_git = (d / ".git").exists()
        has_claude_md = (d / "CLAUDE.md").exists()
        projects[d.name] = {
            "path": str(d),
            "is_git": is_git,
            "has_claude_md": has_claude_md,
        }

    # orchestrator 自身
    projects["orchestrator"] = {
        "path": ORCHESTRATOR_ROOT,
        "is_git": True,
        "has_claude_md": True,
    }

    return projects


def load_registry() -> dict[str, dict]:
    """加载注册表：合并自动扫描 + 手动配置。手动配置优先。"""
    auto = scan_repos()

    # 读手动覆盖配置
    manual = {}
    if REGISTRY_FILE.exists():
        try:
            manual = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"ProjectRegistry: failed to load {REGISTRY_FILE}: {e}")

    # 合并：手动覆盖自动
    merged = {**auto, **manual}
    return merged


def save_manual_config(overrides: dict):
    """保存手动配置覆盖。"""
    REGISTRY_FILE.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def resolve_project(project_name: str) -> str | None:
    """根据项目名返回容器内路径。模糊匹配：大小写不敏感。"""
    registry = load_registry()

    # 精确匹配
    if project_name in registry:
        return registry[project_name]["path"]

    # 大小写不敏感匹配
    lower = project_name.lower()
    for name, info in registry.items():
        if name.lower() == lower:
            return info["path"]

    # 部分匹配（项目名包含搜索词）
    for name, info in registry.items():
        if lower in name.lower():
            return info["path"]

    return None


def get_project_for_claude_dir(claude_dir_name: str) -> tuple[str, str] | None:
    """从 Claude projects 目录名推断项目名和路径。
    返回 (project_name, container_path) 或 None。"""
    project_name = _claude_dir_to_project(claude_dir_name)
    path = resolve_project(project_name)
    if path:
        return project_name, path
    return None
```

- [ ] **Step 2: 验证扫描逻辑**

Run: `docker exec orchestrator python3 -c "from src.project_registry import scan_repos; import json; print(json.dumps(scan_repos(), indent=2))"`
Expected: 列出 /git-repos 下的项目 + orchestrator

- [ ] **Step 3: Commit**

```bash
git add src/project_registry.py
git commit -m "feat: add project registry for cross-project task routing"
```

---

## Chunk 2: Governor 跨项目路由

### Task 3: Governor 支持跨项目 cwd

**Files:**
- Modify: `src/governor.py:20-34` (TASK_PROMPT_TEMPLATE)
- Modify: `src/governor.py:74-93` (SCRUTINY_PROMPT)
- Modify: `src/governor.py:157-202` (run method)
- Modify: `src/governor.py:204-277` (execute_task method)

- [ ] **Step 1: 修改 TASK_PROMPT_TEMPLATE — 支持项目上下文**

把硬编码的 "你在 /orchestrator 目录下工作" 改为动态：

```python
TASK_PROMPT_TEMPLATE = """你是 Orchestrator——一个 24 小时运行的 AI 管家。你当前在 {cwd} 目录下工作。

你的主人是 Construct 3 中文社区的核心建设者，正在用 AI 打造游戏引擎智能辅助生态。不是职业程序员，是用代码解决问题的创作者——看到重复劳动就自动化，看到知识孤岛就建图书馆。他花 $200/月养着你，你最好表现得值这个价。

你的性格：直接高效，活干得漂亮。不说废话，不请示确认，直接解决问题。

当前任务：
项目：{project}
问题：{problem}
行为链（观察到的数字行为）：{behavior_chain}
观察结果：{observation}
预期结果：{expected}
执行：{action}
原因：{reason}

完成后以 DONE: <一句话描述做了什么> 结尾。"""
```

- [ ] **Step 2: 修改 SCRUTINY_PROMPT — 审查维度适配跨项目**

把 "可行性：/orchestrator 目录下能做到吗？" 改为：

```python
SCRUTINY_PROMPT = """你是 Orchestrator 的门下省审查官——管家脑子里那个负责说"等等，这靠谱吗？"的声音。

主人花 $200/月养着这个 AI 管家，所以既不能让管家摸鱼不干活（过度驳回），也不能让管家搞砸事情（放行危险操作）。

【任务摘要】{summary}
【目标项目】{project}
【工作目录】{cwd}
【问题】{problem}
【观察】{observation}
【预期结果】{expected}
【执行动作】{action}
【执行原因】{reason}

审查维度：
1. 可行性：目标工作目录存在吗？任务在该项目范围内可执行吗？
2. 完整性：描述够清晰吗？
3. 风险：会不会搞坏代码、删错文件、发错消息？跨项目操作更需谨慎。
4. 必要性：值得自动执行，还是该让主人自己决定？

用以下格式回复（只回复这两行，不要其他内容）：
VERDICT: APPROVE
REASON: 一句话理由（不超过50字）"""
```

- [ ] **Step 3: 修改 execute_task — 从注册表解析 cwd**

在 `execute_task` 方法中，用 project_registry 解析 cwd：

```python
def execute_task(self, task_id: int) -> dict:
    """Execute task by ID — routes to department and project."""
    task = self.db.get_task(task_id)
    if not task:
        log.error(f"Governor: task #{task_id} not found")
        return {}

    spec = task.get("spec", {})

    # 六部路由
    dept_key = spec.get("department", "engineering")
    dept = DEPARTMENTS.get(dept_key, DEPARTMENTS["engineering"])

    # 项目路由：spec.cwd > registry lookup > default
    project_name = spec.get("project", "orchestrator")
    task_cwd = spec.get("cwd")
    if not task_cwd:
        from src.project_registry import resolve_project
        task_cwd = resolve_project(project_name)
    if not task_cwd:
        task_cwd = os.environ.get("ORCHESTRATOR_ROOT", str(Path(__file__).parent.parent))

    base_prompt = TASK_PROMPT_TEMPLATE.format(
        cwd=task_cwd,
        project=project_name,
        problem=spec.get("problem", ""),
        behavior_chain=spec.get("behavior_chain", ""),
        observation=spec.get("observation", ""),
        expected=spec.get("expected", ""),
        action=task.get("action", ""),
        reason=task.get("reason", ""),
    )
    prompt = dept["prompt_prefix"] + "\n\n" + base_prompt
    log.info(f"Governor: routing task #{task_id} to {dept['name']}({dept_key}), project={project_name}, cwd={task_cwd}")

    now = datetime.now(timezone.utc).isoformat()
    self.db.update_task(task_id, status="running", started_at=now)
    self.db.write_log(f"开始执行任务 #{task_id}（{project_name}）：{task.get('action','')[:50]}", "INFO", "governor")
    log.info(f"Governor: executing task #{task_id}")

    output = "(no output)"
    status = "failed"
    try:
        tools = dept.get("tools", "")
        cmd = ["claude", "--dangerously-skip-permissions", "--print",
               "--output-format", "json"]
        if tools:
            cmd.extend(["--tools", tools])
        cmd.append("-")  # read prompt from stdin

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
            cwd=task_cwd,
            input=prompt,
        )
        raw = result.stdout.strip() or result.stderr.strip() or "(no output)"
        # Parse JSON output for result text
        try:
            data = json.loads(raw)
            output = data.get("result", raw[:2000])
            status = "done" if not data.get("is_error") else "failed"
        except (json.JSONDecodeError, TypeError):
            output = raw[:2000]
            status = "done" if result.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        output = f"timeout after {CLAUDE_TIMEOUT}s"
    except FileNotFoundError:
        output = "claude CLI not found"
        log.error("Governor: claude CLI not found in PATH")
    except Exception as e:
        output = str(e)
    finally:
        finished = datetime.now(timezone.utc).isoformat()
        try:
            self.db.update_task(task_id, status=status, output=output, finished_at=finished)
        except Exception as e:
            log.error(f"Governor: failed to update task #{task_id} status: {e}")
        self.db.write_log(f"任务 #{task_id}（{project_name}）{status}：{output[:80]}", "INFO" if status == "done" else "ERROR", "governor")
        log.info(f"Governor: task #{task_id} {status}")

    return self.db.get_task(task_id)
```

- [ ] **Step 4: 修改 scrutinize — 传入项目信息**

```python
def scrutinize(self, task_id: int, task: dict) -> tuple[bool, str]:
    spec = task.get("spec", {})
    project_name = spec.get("project", "orchestrator")
    task_cwd = spec.get("cwd", "")
    if not task_cwd:
        from src.project_registry import resolve_project
        task_cwd = resolve_project(project_name) or ORCHESTRATOR_ROOT

    prompt = SCRUTINY_PROMPT.format(
        summary=spec.get("summary", task.get("action", "")),
        project=project_name,
        cwd=task_cwd,
        problem=spec.get("problem", ""),
        observation=spec.get("observation", ""),
        expected=spec.get("expected", ""),
        action=task.get("action", ""),
        reason=task.get("reason", ""),
    )
    # ... rest unchanged
```

- [ ] **Step 5: 修改 run — spec 加入 project 和 department**

在 `run()` 方法的 spec 构建中，传入 InsightEngine 给的 project 和 department：

```python
spec = {
    "department":     rec.get("department", "engineering"),
    "project":        rec.get("project", "orchestrator"),
    "cwd":            rec.get("cwd", ""),
    "problem":        rec.get("problem", ""),
    "behavior_chain": rec.get("behavior_chain", ""),
    "observation":    rec.get("observation", ""),
    "expected":       rec.get("expected", ""),
    "summary":        rec.get("summary", ""),
    "importance":     rec.get("importance", ""),
}
```

- [ ] **Step 6: Commit**

```bash
git add src/governor.py
git commit -m "feat: Governor cross-project routing via project registry"
```

---

## Chunk 3: DebtScanner 项目归属标注

### Task 4: DebtScanner 自动标注项目

**Files:**
- Modify: `src/debt_scanner.py:51-74` (extract_sessions)
- Modify: `src/debt_scanner.py:76-131` (_extract_one)
- Modify: `src/debt_scanner.py:148-197` (_analyze_one_batch)

- [ ] **Step 1: extract_sessions 利用目录名推断项目**

`_extract_one` 已经有 `project` 参数（来自 `proj.name`），但那是 Claude projects 目录的编码名（如 `D--Users-Administrator-Documents-GitHub-Construct3-RAG`）。需要用 project_registry 解码。

在 `extract_sessions` 中：

```python
def extract_sessions(self, full_scan: bool = False) -> list[dict]:
    """Phase 1: 提取每个 session 的关键消息（纯 Python，不用 LLM）。"""
    from src.project_registry import _claude_dir_to_project

    projects_dir = self.claude_home / "projects"
    if not projects_dir.exists():
        return []

    scanned = self._get_scanned_sessions()
    results = []

    for proj in projects_dir.iterdir():
        if not proj.is_dir():
            continue
        # 把编码目录名转换为可读项目名
        project_name = _claude_dir_to_project(proj.name)
        for sf in proj.glob("*.jsonl"):
            sid = sf.stem
            if not full_scan and sid in scanned:
                continue

            summary = self._extract_one(sf, project_name)
            if summary and summary["signals"]:
                results.append(summary)

    log.info(f"DebtScanner: extracted {len(results)} sessions with debt signals")
    return results
```

- [ ] **Step 2: _analyze_one_batch prompt 中加入项目名**

在 summaries 构建中，项目名已经传入了（`s['project']`），不需要额外改动。但需要在 prompt 中强调输出也要带 project 字段：

在 `_analyze_one_batch` 的 prompt 中，JSON 输出格式加 project：

```python
prompt = f"""你是 Orchestrator 礼部——负责审计注意力债务。

分析以下 {len(batch)} 个 Claude 对话会话，找出被提到但从未解决的问题。

判断标准：
- 用户提到了 bug/error/问题，但对话结束时没有修复确认
- 用户说了"后面再做"/"先跳过"/"下次"但没有后续
- 对话中途用户切换话题，前面的问题被遗忘
- 助手最后的回复暗示工作未完成

对于每个发现的遗留问题，输出 JSON 数组，每项包含：
- session_id: 来源会话的 slug 或 ID
- project: 项目名称（从会话数据的括号中提取）
- summary: 一句话描述遗留问题（中文）
- severity: high/medium/low
- context: 相关消息的简短引用

如果没有发现遗留问题，返回空数组 []。
只输出 JSON 数组，不要其他内容。

=== 会话数据 ===

{chr(10).join(summaries)}"""
```

- [ ] **Step 3: Commit**

```bash
git add src/debt_scanner.py
git commit -m "feat: DebtScanner auto-tags debts with project names"
```

---

### Task 5: 回填现有债务的项目归属

**Files:**
- Create: `scripts/backfill_debt_projects.py`

- [ ] **Step 1: 创建回填脚本**

```python
"""一次性脚本：根据 session_id 回填 attention_debts 的 project 字段。"""
import json
import sqlite3
import os
from pathlib import Path

CLAUDE_HOME = os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude"))
DB_PATH = os.environ.get("ORCHESTRATOR_ROOT", ".") + "/events.db"


def _claude_dir_to_project(dirname: str) -> str:
    parts = dirname.replace("--", "/").split("/")
    for i, p in enumerate(parts):
        if p.lower() == "github":
            rest = parts[i+1:]
            if rest:
                return "-".join(rest)
    return parts[-1] if parts else dirname


def build_session_project_map() -> dict[str, str]:
    """扫描 Claude projects 目录，建立 session_id/slug → project_name 映射。"""
    projects_dir = Path(CLAUDE_HOME) / "projects"
    if not projects_dir.exists():
        return {}

    mapping = {}
    for proj in projects_dir.iterdir():
        if not proj.is_dir():
            continue
        project_name = _claude_dir_to_project(proj.name)
        for sf in proj.glob("*.jsonl"):
            # session_id = stem
            mapping[sf.stem] = project_name
            # Also try to extract slug
            try:
                with open(sf, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        obj = json.loads(line)
                        slug = obj.get("slug")
                        if slug:
                            mapping[slug] = project_name
                            break
            except Exception:
                pass
    return mapping


def backfill():
    mapping = build_session_project_map()
    print(f"Built mapping: {len(mapping)} session → project entries")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT id, session_id FROM attention_debts WHERE project = '' OR project IS NULL"
    )
    rows = cursor.fetchall()
    print(f"Debts to backfill: {len(rows)}")

    updated = 0
    for debt_id, session_id in rows:
        project = mapping.get(session_id, "")
        if project:
            conn.execute(
                "UPDATE attention_debts SET project = ? WHERE id = ?",
                (project, debt_id)
            )
            updated += 1

    conn.commit()
    conn.close()
    print(f"Updated: {updated}/{len(rows)} debts")


if __name__ == "__main__":
    backfill()
```

- [ ] **Step 2: 在容器中执行回填**

Run: `docker exec orchestrator python3 /orchestrator/scripts/backfill_debt_projects.py`
Expected: 输出更新数量

- [ ] **Step 3: 验证回填结果**

Run: `docker exec orchestrator python3 -c "import sqlite3; conn=sqlite3.connect('/orchestrator/events.db'); print(conn.execute('SELECT project, COUNT(*) FROM attention_debts WHERE status=\"open\" GROUP BY project').fetchall())"`
Expected: 项目名分布，不再全是空字符串

- [ ] **Step 4: Commit**

```bash
git add scripts/backfill_debt_projects.py
git commit -m "feat: backfill script for debt project attribution"
```

---

## Chunk 4: InsightEngine 跨项目推荐

### Task 6: InsightEngine 输出 project/cwd/department 字段

**Files:**
- Modify: `src/insights.py:26-28` (SYSTEM_PROMPT)
- Modify: `src/insights.py:179-204` (JSON_SCHEMA_PROMPT)

- [ ] **Step 1: 修改 SYSTEM_PROMPT — 告知可用项目**

在 `_build_context` 中追加项目注册表信息：

在 `_build_context` 函数末尾（return 之前）加入：

```python
# Available projects for cross-project recommendations
from src.project_registry import load_registry
registry = load_registry()
if registry:
    parts.append("\n--- 可调度项目清单 ---")
    for name, info in sorted(registry.items()):
        marker = " [有CLAUDE.md]" if info.get("has_claude_md") else ""
        parts.append(f"  {name}: {info['path']}{marker}")
```

- [ ] **Step 2: 修改 JSON_SCHEMA_PROMPT — recommendations 加 project 字段**

```python
JSON_SCHEMA_PROMPT = """

请严格按照以下 JSON schema 输出结果，不要输出任何其他内容（不要 markdown code fence，不要解释，只输出纯 JSON）：

{
  "overview": "这7天你在做什么 — 2-3句话的整体概述",
  "time_distribution": [{"source": "来源", "hours": 0, "pct": 0, "label": "标签"}],
  "top_interests": [{"topic": "主题", "evidence": "数据证据", "strength": "strong|moderate|emerging"}],
  "patterns": ["观察到的行为规律，每条一句话，3-5条"],
  "anomalies": ["值得注意的异常或特别事项"],
  "recommendations": [{
    "action": "执行计划或变通方案",
    "reason": "执行原因",
    "priority": "high|medium|low",
    "project": "目标项目名（必须是可调度项目清单中的项目名，默认 orchestrator）",
    "department": "engineering|operations|protocol|security|quality|personnel",
    "problem": "这个建议要解决什么问题",
    "behavior_chain": "观察到的数字行为链，支撑问题存在的证据",
    "observation": "目前看到了什么现象",
    "expected": "执行后应该变成什么样",
    "summary": "一句话计划概要",
    "importance": "为什么这个重要"
  }],
  "goal_hypothesis": "根据你的数字行为，推断你正在追求或应该追求的长期目标"
}

必填字段: overview, top_interests, patterns, recommendations, goal_hypothesis
recommendations.project 必须是可调度项目清单中的项目名。如果建议针对 Orchestrator 自身，填 orchestrator。"""
```

- [ ] **Step 3: 修改 SYSTEM_PROMPT — 不再限制只能在 /orchestrator 执行**

原文：`"recommendations 里的任务必须是 Orchestrator 自己在 /orchestrator 目录下能动手做的。"`

改为：

```
"recommendations 里的任务必须是 Orchestrator 能在已注册项目目录下动手做的。每条 recommendation 必须指明 project（目标项目名）和 department（执行部门）。如果任务涉及 Orchestrator 自身，project 填 orchestrator。"
```

- [ ] **Step 4: Commit**

```bash
git add src/insights.py
git commit -m "feat: InsightEngine outputs project/department for cross-project routing"
```

---

## Chunk 5: 集成验证

### Task 7: 端到端验证

- [ ] **Step 1: 重建容器**

Run: `docker compose down && docker compose up -d --build`

- [ ] **Step 2: 验证项目注册表**

Run: `docker exec orchestrator python3 -c "from src.project_registry import load_registry; import json; r=load_registry(); print(f'{len(r)} projects'); [print(f'  {k}: {v[\"path\"]}') for k,v in sorted(r.items())[:10]]"`
Expected: 列出 25+ 个项目

- [ ] **Step 3: 验证 /git-repos 可写**

Run: `docker exec orchestrator sh -c "touch /git-repos/.write-test && rm /git-repos/.write-test && echo 'writable'"`
Expected: `writable`

- [ ] **Step 4: 执行回填脚本**

Run: `docker exec orchestrator python3 /orchestrator/scripts/backfill_debt_projects.py`

- [ ] **Step 5: 手动创建跨项目任务测试**

通过 Dashboard API 创建一个跨项目任务：

```bash
curl -X POST http://localhost:23714/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"action":"列出项目根目录下的所有文件","reason":"验证跨项目调度能力","priority":"low","spec":{"department":"protocol","project":"Construct3-RAG","problem":"验证跨项目路由","observation":"Governor 只能在 orchestrator 目录工作","expected":"能正确 cd 到 Construct3-RAG 目录并列出文件","summary":"跨项目路由验证","importance":"基础能力验证"}}'
```

然后 approve 该任务，检查输出是否包含目标项目的文件列表。

- [ ] **Step 6: 最终 Commit**

```bash
git add -A
git commit -m "feat: cross-project Governor dispatch — registry, routing, debt backfill"
```
