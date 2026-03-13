# Dashboard Enhancement v2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 dashboard 添加 7 个新信息模块（用户画像、深度画像分析、7日趋势、热力图、分类统计、任务统计、事件搜索）并引入定期+按需的 ProfileAnalyst 深度分析能力。

**Architecture:** 扁平化扩展：Python 新增 `ProfileAnalyst` 类和 CLI 入口，Node 新增 5 个 GET/POST 端点，前端在现有 grid 中追加 7 张新卡片，沿用极简黑色风格，零额外依赖。所有 innerHTML 赋值均通过现有 `esc()` 函数转义用户来源内容，防止 XSS（与项目既有模式一致）。

**Tech Stack:** Python 3 + sqlite3 + APScheduler + Anthropic SDK；Node.js + Express + sql.js + WebSocket；原生 HTML/CSS/JS（无框架）

**Spec:** `docs/superpowers/specs/2026-03-13-dashboard-enhance-v2-design.md`

---

## File Map

| 操作 | 路径 | 职责 |
|------|------|------|
| Modify | `src/storage/events_db.py` | 新增 `profile_analysis` 表 + 4 个查询方法 |
| Create | `src/profile_analyst.py` | `ProfileAnalyst` 类：构建上下文 → 调用 Claude → 存库 |
| Create | `src/profile_analyst_cli.py` | Node spawn 调用入口，输出 JSON |
| Modify | `src/scheduler.py` | 新增 interval(6h) + cron(06:00 CST) 两个 job |
| Modify | `dashboard/server.js` | 新增 5 个 API 端点 |
| Modify | `dashboard/public/index.html` | 新增 CSS + 7 个 UI 模块 |
| Modify | `tests/test_events_db.py` | 新增 profile_analysis 相关测试 |

**XSS 安全说明：** 前端所有动态内容（AI 生成文本、数据库字段、用户输入过滤结果）均经过 `esc()` 函数 HTML 转义后再写入 innerHTML，与项目现有模式（`index.html` 500+ 行中贯穿使用）完全一致。

---

## Chunk 1: Python 层

### Task 1: events_db.py — 新增表和查询方法

**Files:**
- Modify: `src/storage/events_db.py`
- Modify: `tests/test_events_db.py`

- [ ] **Step 1: 写测试（先失败）**

在 `tests/test_events_db.py` 末尾追加：

```python
def test_profile_analysis_table_exists(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    assert "profile_analysis" in db.get_tables()


def test_save_and_get_profile_analysis(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    data = {"overview": "测试概述", "strengths": ["专注"], "type": "periodic"}
    db.save_profile_analysis(data, "periodic")
    result = db.get_profile_analysis()
    assert result["overview"] == "测试概述"
    assert result["type"] == "periodic"


def test_profile_analysis_pruning(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    for i in range(55):
        db.save_profile_analysis({"overview": f"entry {i}"}, "periodic")
    with db._connect() as conn:
        count = conn.execute("SELECT COUNT(*) as c FROM profile_analysis").fetchone()["c"]
    assert count == 50


def test_get_events_by_day(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "test", 10, 0.5, [], {})
    result = db.get_events_by_day(days=7)
    assert len(result) == 1
    assert "day" in result[0]
    assert "count" in result[0]
    assert result[0]["count"] == 1


def test_get_events_by_category(tmp_path):
    db = EventsDB(str(tmp_path / "events.db"))
    db.insert_event("claude", "coding", "test1", 30, 0.5, [], {})
    db.insert_event("browser", "reading", "test2", 20, 0.5, [], {})
    result = db.get_events_by_category(days=7)
    categories = {r["category"] for r in result}
    assert "coding" in categories
    assert "reading" in categories
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /d/Users/Administrator/Documents/GitHub/orchestrator
python -m pytest tests/test_events_db.py::test_profile_analysis_table_exists -v
```

预期：`FAILED` — AttributeError 或 AssertionError

- [ ] **Step 3: 在 `_init_tables` executescript 末尾追加表定义**

找到 `scheduler_status` 表定义后（约第 89 行），在 `"""` 闭合之前插入：

```sql
                CREATE TABLE IF NOT EXISTS profile_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_json TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'periodic',
                    generated_at TEXT NOT NULL
                );
```

- [ ] **Step 4: 在 `events_db.py` 末尾（`get_running_task` 方法之后）追加 4 个方法**

```python
def save_profile_analysis(self, data: dict, analysis_type: str = 'periodic'):
    now = datetime.now(timezone.utc).isoformat()
    data_copy = dict(data)
    data_copy['generated_at'] = now
    data_copy['type'] = analysis_type
    with self._connect() as conn:
        conn.execute(
            "INSERT INTO profile_analysis (data_json, type, generated_at) VALUES (?, ?, ?)",
            (json.dumps(data_copy, ensure_ascii=False), analysis_type, now)
        )
        conn.execute(
            "DELETE FROM profile_analysis WHERE id NOT IN "
            "(SELECT id FROM profile_analysis ORDER BY id DESC LIMIT 50)"
        )

def get_profile_analysis(self, analysis_type: str = None) -> dict:
    with self._connect() as conn:
        if analysis_type:
            row = conn.execute(
                "SELECT data_json FROM profile_analysis WHERE type = ? ORDER BY id DESC LIMIT 1",
                (analysis_type,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT data_json FROM profile_analysis ORDER BY id DESC LIMIT 1"
            ).fetchone()
    return json.loads(row["data_json"]) if row else {}

def get_events_by_day(self, days: int = 60) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT DATE(occurred_at) as day, COUNT(*) as count "
            "FROM events WHERE occurred_at >= ? GROUP BY DATE(occurred_at) ORDER BY day ASC",
            (since,)
        ).fetchall()
    return [dict(r) for r in rows]

def get_events_by_category(self, days: int = 7) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with self._connect() as conn:
        rows = conn.execute(
            "SELECT category, SUM(duration_minutes) as total_min, COUNT(*) as count "
            "FROM events WHERE occurred_at >= ? GROUP BY category ORDER BY total_min DESC",
            (since,)
        ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: 运行全部新测试，确认通过**

```bash
python -m pytest tests/test_events_db.py -v -k "profile or category or day"
```

预期：5 个测试全部 PASSED

- [ ] **Step 6: 运行完整测试套件确认无回归**

```bash
python -m pytest tests/test_events_db.py -v
```

预期：全部 PASSED

- [ ] **Step 7: 提交**

```bash
git add src/storage/events_db.py tests/test_events_db.py
git commit -m "feat: add profile_analysis table and query methods to EventsDB"
```

---

### Task 2: profile_analyst.py — ProfileAnalyst 类

**Files:**
- Create: `src/profile_analyst.py`

- [ ] **Step 1: 创建 `src/profile_analyst.py`**

```python
"""
ProfileAnalyst — 深度用户画像分析引擎。
periodic: 分析最近 30 天数据，每 6 小时运行一次。
daily:    分析昨天数据，每日 06:00 CST 运行。
"""
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from src.config import get_anthropic_client
from src.storage.events_db import EventsDB

PROFILE_TOOL = {
    "name": "save_profile_analysis",
    "description": "保存深度用户画像分析结果",
    "input_schema": {
        "type": "object",
        "properties": {
            "overview": {
                "type": "string",
                "description": "对用户这段时间整体状态的印象（200字以内，直接、有洞察力）"
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "从数据中观察到的用户优点、特质或能力（3-5条）"
            },
            "blind_spots": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可能的盲区、值得警惕的模式或被忽视的事项（2-4条）"
            },
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "具体可执行的建议"},
                        "reason": {"type": "string", "description": "建议的理由和数据依据"},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]}
                    },
                    "required": ["action", "reason", "priority"]
                },
                "description": "3-5 条有针对性的建议，基于数据"
            },
            "commentary": {
                "type": "string",
                "description": "AI 的自由评论：想法、感受、有趣的观察，语气自然随意（100-200字）"
            },
            "daily_note": {
                "type": "string",
                "description": "仅限 daily 类型：对昨天这一天的专属点评（100字以内），periodic 类型留空字符串"
            }
        },
        "required": ["overview", "strengths", "blind_spots", "suggestions", "commentary", "daily_note"]
    }
}

SYSTEM_PROMPT = """你是用户的私人生活顾问，正在分析他的数字行为数据，给出深度的个人化分析。

你的风格：
- 直接、坦诚，不说废话
- 基于数据说话，但能看到数据背后的人
- 既能欣赏用户的优点，也敢指出值得改进的地方
- commentary 部分可以有个性，像朋友聊天而非机器报告
- 不要重复陈述数字，要给出洞察

你的目标是帮助用户更好地了解自己。"""


def _build_context(db: EventsDB, analysis_type: str = 'periodic') -> str:
    if analysis_type == 'daily':
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        events = [
            e for e in db.get_recent_events(days=2)
            if e['occurred_at'][:10] == yesterday
        ]
        date_range = f"昨天（{yesterday}）"
    else:
        events = db.get_recent_events(days=30)
        date_range = "最近 30 天"

    profile = db.get_latest_profile()
    summaries = db.get_daily_summaries(days=7)

    parts = [f"=== 用户数字行为数据（{date_range}）===\n"]
    parts.append(f"事件总数: {len(events)}")

    by_source = defaultdict(lambda: {"count": 0, "minutes": 0.0, "titles": []})
    for e in events:
        src = e["source"]
        by_source[src]["count"] += 1
        by_source[src]["minutes"] += e.get("duration_minutes") or 0
        if len(by_source[src]["titles"]) < 8:
            by_source[src]["titles"].append(e.get("title", ""))

    parts.append("\n--- 各来源统计 ---")
    for src, stats in sorted(by_source.items(), key=lambda x: -x[1]["minutes"]):
        hours = stats["minutes"] / 60
        parts.append(f"{src}: {stats['count']}条, {hours:.1f}小时")
        if stats["titles"]:
            parts.append("  样本: " + " | ".join(t[:40] for t in stats["titles"][:4] if t))

    if profile:
        parts.append(f"\n--- 当前用户画像 ---\n{json.dumps(profile, ensure_ascii=False, indent=2)[:600]}")

    if summaries and analysis_type == 'periodic':
        parts.append("\n--- 近期每日摘要 ---")
        for s in summaries[:5]:
            parts.append(f"[{s['date']}] {s.get('summary', '')[:80]}")

    return "\n".join(parts)


class ProfileAnalyst:
    def __init__(self, db: EventsDB = None, db_path: str = "events.db"):
        self.client = get_anthropic_client()
        self.db = db or EventsDB(db_path)

    def run(self, analysis_type: str = 'periodic') -> dict:
        context = _build_context(self.db, analysis_type)

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=[PROFILE_TOOL],
            tool_choice={"type": "tool", "name": "save_profile_analysis"},
            messages=[{"role": "user", "content": context}],
        )

        block = next(b for b in response.content if b.type == "tool_use")
        result = block.input
        self.db.save_profile_analysis(result, analysis_type)
        return result


if __name__ == "__main__":
    analyst = ProfileAnalyst()
    result = analyst.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

- [ ] **Step 2: 验证语法**

```bash
cd /d/Users/Administrator/Documents/GitHub/orchestrator
python -c "from src.profile_analyst import ProfileAnalyst; print('OK')"
```

预期：`OK`

- [ ] **Step 3: 提交**

```bash
git add src/profile_analyst.py
git commit -m "feat: add ProfileAnalyst for deep user profile analysis"
```

---

### Task 3: profile_analyst_cli.py — CLI 入口

**Files:**
- Create: `src/profile_analyst_cli.py`

- [ ] **Step 1: 创建 `src/profile_analyst_cli.py`**

```python
#!/usr/bin/env python3
"""CLI bridge called by Node dashboard to trigger on-demand profile analysis."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.profile_analyst import ProfileAnalyst
from src.storage.events_db import EventsDB

DB_PATH = str(Path(__file__).parent.parent / "events.db")

VALID_TYPES = ("periodic", "daily")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in VALID_TYPES:
        print(json.dumps({"error": f"usage: profile_analyst_cli.py [{'|'.join(VALID_TYPES)}]"}))
        sys.exit(1)

    analysis_type = sys.argv[1]
    try:
        db = EventsDB(DB_PATH)
        analyst = ProfileAnalyst(db=db)
        result = analyst.run(analysis_type=analysis_type)
        print(json.dumps({"status": "ok", "generated_at": result.get("generated_at", "")}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证 CLI 接口**

```bash
python src/profile_analyst_cli.py
```

预期：`{"error": "usage: profile_analyst_cli.py [periodic|daily]"}`

- [ ] **Step 3: 提交**

```bash
git add src/profile_analyst_cli.py
git commit -m "feat: add profile_analyst_cli.py for Node spawn interface"
```

---

### Task 4: scheduler.py — 注册两个新 job

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: 在顶部 import 区追加（在 `from src.governor import Governor` 下方）**

```python
from src.profile_analyst import ProfileAnalyst
```

- [ ] **Step 2: 在 `start()` 函数中，`def _analysis():` 块末尾之后、`scheduler.add_job` 之前，追加两个新函数**

```python
    def _profile_periodic():
        db = EventsDB(DB_PATH)
        try:
            db.write_log("开始周期性画像分析", "INFO", "profile_analyst")
            analyst = ProfileAnalyst(db=db)
            analyst.run(analysis_type='periodic')
            db.write_log("周期性画像分析完成", "INFO", "profile_analyst")
        except Exception as e:
            log.error(f"ProfileAnalyst periodic failed: {e}")
            db.write_log(f"画像分析失败: {e}", "ERROR", "profile_analyst")

    def _profile_daily():
        db = EventsDB(DB_PATH)
        try:
            db.write_log("开始晨报画像分析（昨日）", "INFO", "profile_analyst")
            analyst = ProfileAnalyst(db=db)
            analyst.run(analysis_type='daily')
            db.write_log("晨报画像分析完成", "INFO", "profile_analyst")
        except Exception as e:
            log.error(f"ProfileAnalyst daily failed: {e}")
            db.write_log(f"晨报画像分析失败: {e}", "ERROR", "profile_analyst")
```

- [ ] **Step 3: 在 `scheduler.add_job(_analysis, ...)` 行之后追加**

```python
    scheduler.add_job(_profile_periodic, "interval", hours=6, id="profile_periodic")
    scheduler.add_job(_profile_daily, "cron", hour=6, timezone="Asia/Shanghai", id="profile_daily")
```

- [ ] **Step 4: 更新启动日志**

将：
```python
    db.write_log("调度器已启动，采集：每小时，分析：每6小时", "INFO", "scheduler")
```
改为：
```python
    db.write_log("调度器已启动，采集：每小时，分析：每6小时，画像分析：每6小时+每日06:00", "INFO", "scheduler")
```

- [ ] **Step 5: 验证语法**

```bash
python -c "from src.scheduler import start; print('OK')"
```

预期：`OK`

- [ ] **Step 6: 提交**

```bash
git add src/scheduler.py
git commit -m "feat: add ProfileAnalyst periodic and daily jobs to scheduler"
```

---

## Chunk 2: Node API 层

### Task 5: server.js — 5 个新端点

**Files:**
- Modify: `dashboard/server.js`

在现有 `/api/schedule-status` 端点之后、`/api/logs` SSE 端点之前，追加以下 5 个端点。注意：`spawn` 已在文件顶部通过 `const { spawn } = require('child_process')` 引入，无需重复引入。

- [ ] **Step 1: 追加 `GET /api/profile-analysis`**

```javascript
app.get('/api/profile-analysis', (req, res) => {
  const db = getDb();
  if (!db) return res.json({});
  try {
    const row = dbAll(db, "SELECT data_json FROM profile_analysis ORDER BY id DESC LIMIT 1");
    res.json(row[0] ? JSON.parse(row[0].data_json) : {});
  } catch { res.json({}); }
  finally { db.close(); }
});
```

- [ ] **Step 2: 追加 `POST /api/profile-analysis/refresh`**

```javascript
app.post('/api/profile-analysis/refresh', (req, res) => {
  res.status(202).json({ status: 'accepted' });

  const proc = spawn('python3', ['/orchestrator/src/profile_analyst_cli.py', 'periodic']);

  const timer = setTimeout(() => {
    proc.kill();
    broadcast({ type: 'profile_analysis_error', error: 'timeout' });
  }, 60000);

  let out = '';
  proc.stdout.on('data', d => { out += d; });
  proc.stderr.on('data', () => {}); // drain stderr to prevent buffer stall (matches pattern in POST /api/tasks)
  proc.on('close', () => {
    clearTimeout(timer);
    try {
      const result = JSON.parse(out);
      if (result.error) {
        broadcast({ type: 'profile_analysis_error', error: result.error });
      } else {
        broadcast({ type: 'profile_analysis_done' });
      }
    } catch {
      broadcast({ type: 'profile_analysis_error', error: 'parse error' });
    }
  });
});
```

- [ ] **Step 3: 追加 `GET /api/events/heatmap`**

```javascript
app.get('/api/events/heatmap', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  const days = parseInt(req.query.days) || 60;
  const since = new Date(Date.now() - days * 86400000).toISOString();
  try {
    const rows = dbAll(db,
      "SELECT DATE(occurred_at) as day, COUNT(*) as count FROM events WHERE occurred_at >= ? GROUP BY DATE(occurred_at) ORDER BY day ASC",
      [since]
    );
    res.json(rows);
  } catch { res.json([]); }
  finally { db.close(); }
});
```

- [ ] **Step 4: 追加 `GET /api/summaries`**

```javascript
app.get('/api/summaries', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  try {
    const rows = dbAll(db,
      "SELECT date, summary FROM daily_summaries ORDER BY date DESC LIMIT 7"
    );
    res.json(rows.map(r => {
      try { return { date: r.date, ...JSON.parse(r.summary) }; }
      catch { return { date: r.date, summary: r.summary }; }
    }));
  } catch { res.json([]); }
  finally { db.close(); }
});
```

- [ ] **Step 5: 追加 `GET /api/stats/categories`**

```javascript
app.get('/api/stats/categories', (req, res) => {
  const db = getDb();
  if (!db) return res.json([]);
  const days = parseInt(req.query.days) || 7;
  const since = new Date(Date.now() - days * 86400000).toISOString();
  try {
    const rows = dbAll(db,
      "SELECT category, SUM(duration_minutes) as total_min, COUNT(*) as count FROM events WHERE occurred_at >= ? GROUP BY category ORDER BY total_min DESC",
      [since]
    );
    res.json(rows);
  } catch { res.json([]); }
  finally { db.close(); }
});
```

- [ ] **Step 6: 验证服务器语法**

```bash
node -e "require('./dashboard/server.js')" 2>&1 | head -3
```

预期：服务器启动日志，无语法错误

- [ ] **Step 7: 验证新端点可达（需要先启动服务器）**

```bash
# 另开终端：node dashboard/server.js
curl -s http://localhost:23714/api/profile-analysis
curl -s "http://localhost:23714/api/events/heatmap?days=7"
curl -s http://localhost:23714/api/summaries
curl -s "http://localhost:23714/api/stats/categories?days=7"
```

预期：各端点返回 `{}` 或 `[]`，HTTP 200，无错误

- [ ] **Step 8: 提交**

```bash
git add dashboard/server.js
git commit -m "feat: add profile-analysis, heatmap, summaries, categories API endpoints"
```

---

## Chunk 3: 前端层

**XSS 安全约定（贯穿所有前端任务）：** 所有 AI 生成内容、数据库字段值、URL 参数值写入 innerHTML 时，必须先通过 `esc()` 函数转义。仅结构性 HTML 标签（div、span 等）可直接拼接，不含用户数据的静态字符串无需转义。

### Task 6: index.html — CSS 新增

**Files:**
- Modify: `dashboard/public/index.html`

- [ ] **Step 1: 在现有 `<style>` 块末尾（`</style>` 之前）追加新 CSS**

```css
/* ── Profile basic card ── */
.profile-field { margin: 6px 0; }
.profile-key { font-size: 0.6rem; text-transform: uppercase; color: #2e2e2e; letter-spacing: 1px; }
.profile-val { font-size: 0.8rem; color: #777; margin-top: 2px; }

/* ── Deep profile analysis card ── */
.analysis-overview { font-size: 0.86rem; line-height: 1.8; color: #bbb; margin-bottom: 14px; border-left: 2px solid #2a2a3a; padding-left: 12px; }
.analysis-section { font-size: 0.6rem; text-transform: uppercase; color: #333; letter-spacing: 1px; margin: 14px 0 6px; }
.analysis-item { font-size: 0.8rem; color: #777; padding: 4px 0; border-bottom: 1px solid #161616; line-height: 1.6; }
.analysis-item:last-child { border-bottom: none; }
.analysis-item::before { content: '·'; color: #2a2a3a; margin-right: 6px; }
.analysis-suggestion { padding: 7px 0; border-bottom: 1px solid #161616; }
.analysis-suggestion:last-child { border-bottom: none; }
.suggestion-action { font-size: 0.82rem; color: #ccc; }
.suggestion-reason { font-size: 0.72rem; color: #444; margin-top: 2px; line-height: 1.5; }
.analysis-commentary { font-size: 0.82rem; color: #666; line-height: 1.75; font-style: italic; background: #0d0d0d; padding: 10px 12px; border-radius: 3px; margin-top: 6px; }
.analysis-daily-note { font-size: 0.82rem; color: #5a7a9a; line-height: 1.7; padding: 8px 12px; background: #0d1017; border-radius: 3px; border-left: 2px solid #2a3a4a; }
.btn-refresh { font-size: 0.6rem; padding: 2px 8px; border-radius: 2px; border: 1px solid #2a2a3a; background: #0a0a12; color: #4a4a7a; cursor: pointer; }
.btn-refresh:hover { background: #12121e; color: #8a8ab0; }
.btn-refresh:disabled { opacity: 0.4; cursor: not-allowed; }
.analysis-meta { font-size: 0.62rem; color: #2a2a2a; margin-top: 10px; }
.type-badge { font-size: 0.58rem; padding: 1px 5px; border-radius: 2px; background: #12121a; color: #3a3a5a; margin-right: 6px; }

/* ── 7-day trend ── */
.trend-row { display: flex; align-items: flex-start; padding: 7px 0; border-bottom: 1px solid #161616; gap: 10px; }
.trend-row:last-child { border-bottom: none; }
.trend-date { font-size: 0.68rem; color: #333; min-width: 48px; flex-shrink: 0; padding-top: 2px; }
.trend-topics { display: flex; flex-wrap: wrap; gap: 3px; flex: 1; }
.trend-summary { font-size: 0.72rem; color: #444; margin-top: 3px; line-height: 1.5; }

/* ── Heatmap ── */
.heatmap-grid { display: flex; gap: 2px; margin-top: 8px; flex-wrap: nowrap; overflow-x: auto; }
.heatmap-col { display: flex; flex-direction: column; gap: 2px; }
.heatmap-cell { width: 11px; height: 11px; border-radius: 2px; background: #141414; cursor: pointer; transition: opacity 0.1s; flex-shrink: 0; }
.heatmap-cell:hover { opacity: 0.7; }
.heatmap-cell.lv1 { background: #1a2a1a; }
.heatmap-cell.lv2 { background: #2a4a2a; }
.heatmap-cell.lv3 { background: #3a6a3a; }
.heatmap-cell.lv4 { background: #4a8a4a; }
.heatmap-detail { font-size: 0.72rem; color: #444; margin-top: 10px; min-height: 20px; }
.heatmap-labels { display: flex; justify-content: space-between; margin-top: 4px; }
.heatmap-label { font-size: 0.58rem; color: #222; }

/* ── Category stats ── */
.cat-toggle { display: flex; gap: 4px; margin-bottom: 12px; }
.cat-btn { font-size: 0.6rem; padding: 2px 8px; border-radius: 2px; border: 1px solid #1e1e1e; background: #0a0a0a; color: #333; cursor: pointer; }
.cat-btn.active { border-color: #2a2a3a; color: #6a6a9a; background: #101018; }
.cat-bar-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.cat-bar-label { font-size: 0.7rem; color: #555; min-width: 80px; flex-shrink: 0; }
.cat-bar-track { flex: 1; height: 3px; background: #141414; border-radius: 2px; overflow: hidden; }
.cat-bar-fill { height: 100%; border-radius: 2px; }
.cat-bar-val { font-size: 0.65rem; color: #333; min-width: 40px; text-align: right; flex-shrink: 0; }

/* ── Task stats mini bar ── */
.task-stats-bar { display: flex; gap: 16px; padding: 8px 0 12px; border-bottom: 1px solid #161616; margin-bottom: 4px; }
.task-stat-item { font-size: 0.68rem; color: #333; }
.task-stat-num { font-size: 1.1rem; font-weight: 200; color: #888; display: block; }

/* ── Event search ── */
.event-search-bar { display: flex; gap: 6px; margin-bottom: 10px; }
.event-search-input { flex: 1; background: #0d0d0d; border: 1px solid #1e1e1e; border-radius: 3px; padding: 4px 8px; color: #888; font-size: 0.72rem; outline: none; }
.event-search-input::placeholder { color: #2a2a2a; }
.event-search-input:focus { border-color: #2a2a3a; }
.event-src-select { background: #0d0d0d; border: 1px solid #1e1e1e; border-radius: 3px; padding: 4px 6px; color: #555; font-size: 0.68rem; outline: none; }
```

- [ ] **Step 2: 提交 CSS**

```bash
git add dashboard/public/index.html
git commit -m "feat: add CSS for 7 new dashboard modules"
```

---

### Task 7: index.html — 模块 1-4（HTML 骨架 + 渲染函数）

**Files:**
- Modify: `dashboard/public/index.html`

- [ ] **Step 1: 在 `深度洞察` 卡片之前插入模块 1（用户画像基础）和模块 2（深度画像分析）骨架**

找到 `<div class="card wide" id="insights-card">`，在其之前插入：

```html
  <!-- Profile Basic Card -->
  <div class="card" id="profile-card">
    <h2>用户画像</h2>
    <div id="profile-basic"><div class="no-data">等待首次分析</div></div>
  </div>

  <!-- Deep Profile Analysis Card -->
  <div class="card wide" id="profile-analysis-card">
    <h2 style="display:flex;justify-content:space-between;align-items:center">
      深度画像分析
      <span style="display:flex;gap:8px;align-items:center">
        <span id="analysis-meta" class="dim"></span>
        <button id="btn-refresh-analysis" class="btn-refresh" onclick="refreshAnalysis()">刷新</button>
      </span>
    </h2>
    <div id="profile-analysis"><div class="no-data">等待首次生成（每6小时更新）</div></div>
  </div>
```

- [ ] **Step 2: 在 `<!-- Tasks Panel -->` 之前插入模块 3（7日趋势）和模块 4（热力图）骨架**

```html
  <!-- 7-Day Trend Summary -->
  <div class="card" id="trend-card">
    <h2>7 日趋势</h2>
    <div id="trend-list"><div class="no-data">等待数据</div></div>
  </div>

  <!-- Activity Heatmap -->
  <div class="card" id="heatmap-card">
    <h2>活动热力图 <span class="dim" style="font-size:0.58rem">近 60 天</span></h2>
    <div id="heatmap-grid"></div>
    <div class="heatmap-labels">
      <span class="heatmap-label" id="heatmap-start"></span>
      <span class="heatmap-label" id="heatmap-end"></span>
    </div>
    <div id="heatmap-detail" class="heatmap-detail"></div>
  </div>
```

- [ ] **Step 3: 在 `<script>` 中 `function esc(s)` 之后追加模块 1-4 渲染函数**

注意：所有动态内容均经 `esc()` 转义后再写入 innerHTML。

```javascript
// ── Module 1: Profile Basic ──────────────────────────────────
// All user data goes through esc() before being set as innerHTML
function renderProfileBasic(profile) {
  if (!profile || !Object.keys(profile).length) {
    return '<div class="no-data">等待首次分析</div>';
  }
  return Object.entries(profile).map(([k, v]) => {
    const val = Array.isArray(v)
      ? v.map(t => `<span class="tag">${esc(String(t))}</span>`).join('')
      : `<span class="profile-val">${esc(String(v))}</span>`;
    return `<div class="profile-field"><div class="profile-key">${esc(k)}</div>${val}</div>`;
  }).join('');
}

// ── Module 2: Deep Profile Analysis ─────────────────────────
// All AI-generated content goes through esc() before innerHTML
function renderProfileAnalysis(d) {
  if (!d || !d.overview) return '<div class="no-data">等待首次生成（每6小时更新）</div>';
  let html = `<div class="analysis-overview">${esc(d.overview)}</div>`;

  if (d.strengths?.length) {
    html += `<div class="analysis-section">优点 / 特质</div>`;
    html += d.strengths.map(s => `<div class="analysis-item">${esc(s)}</div>`).join('');
  }
  if (d.blind_spots?.length) {
    html += `<div class="analysis-section">盲区 / 值得注意</div>`;
    html += d.blind_spots.map(s => `<div class="analysis-item">${esc(s)}</div>`).join('');
  }
  if (d.suggestions?.length) {
    html += `<div class="analysis-section">建议</div>`;
    html += d.suggestions.map(s => `
      <div class="analysis-suggestion">
        <div class="suggestion-action">${esc(s.action)}<span class="priority priority-${esc(s.priority)}">${esc(s.priority)}</span></div>
        <div class="suggestion-reason">${esc(s.reason)}</div>
      </div>`).join('');
  }
  if (d.commentary) {
    html += `<div class="analysis-section">AI 点评</div>`;
    html += `<div class="analysis-commentary">${esc(d.commentary)}</div>`;
  }
  if (d.daily_note) {
    html += `<div class="analysis-section">昨日专属</div>`;
    html += `<div class="analysis-daily-note">${esc(d.daily_note)}</div>`;
  }
  return html;
}

// ── Module 3: 7-Day Trend ────────────────────────────────────
// All data fields go through esc() before innerHTML
function renderTrend(summaries) {
  if (!summaries?.length) return '<div class="no-data">等待数据</div>';
  return summaries.map(s => {
    const topics = (s.top_topics || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
    const date = esc((s.date || '').slice(5));
    return `<div class="trend-row">
      <span class="trend-date">${date}</span>
      <div>
        <div class="trend-topics">${topics || '<span class="dim">—</span>'}</div>
        ${s.behavioral_insights ? `<div class="trend-summary">${esc(s.behavioral_insights.slice(0, 60))}</div>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ── Module 4: Heatmap ────────────────────────────────────────
// Heatmap cell day values come from API (ISO dates) — safe for data attributes
// count values are integers — safe to use directly
// showHeatmapDay uses esc() for event titles
let _heatmapData = {};
let _eventsCache = [];

function renderHeatmap(data) {
  _heatmapData = Object.fromEntries(data.map(d => [d.day, Number(d.count)]));
  const today = new Date();
  const start = new Date(today);
  start.setDate(start.getDate() - 59);
  const dayOfWeek = start.getDay() || 7;
  start.setDate(start.getDate() - (dayOfWeek - 1));

  const columns = [];
  const cur = new Date(start);
  let col = [];
  while (cur <= today) {
    const iso = cur.toISOString().slice(0, 10);
    const count = _heatmapData[iso] || 0;
    const lv = count === 0 ? 0 : count <= 3 ? 1 : count <= 9 ? 2 : count <= 19 ? 3 : 4;
    col.push({ iso, count, lv });
    if (col.length === 7) { columns.push(col); col = []; }
    cur.setDate(cur.getDate() + 1);
  }
  if (col.length) columns.push(col);

  const grid = document.getElementById('heatmap-grid');
  grid.className = 'heatmap-grid';
  // ISO date strings from API are safe; count is integer
  grid.innerHTML = columns.map(c =>
    `<div class="heatmap-col">${c.map(d =>
      `<div class="heatmap-cell lv${d.lv}" data-day="${d.iso}" data-count="${d.count}"
           onclick="showHeatmapDay('${d.iso}',${d.count})"
           title="${d.iso}: ${d.count}条"></div>`
    ).join('')}</div>`
  ).join('');

  const startLabel = start.toLocaleDateString('zh-CN', {month:'numeric',day:'numeric'});
  const endLabel = today.toLocaleDateString('zh-CN', {month:'numeric',day:'numeric'});
  document.getElementById('heatmap-start').textContent = startLabel;
  document.getElementById('heatmap-end').textContent = endLabel;
}

function showHeatmapDay(day, count) {
  const detail = document.getElementById('heatmap-detail');
  if (!count) { detail.textContent = `${day}：无数据`; return; }
  // Filter from events cache; event titles go through esc()
  const dayEvents = _eventsCache.filter(e => (e.occurred_at || '').slice(0, 10) === day);
  const top5 = dayEvents.slice(0, 5).map(e => esc(e.title || '').slice(0, 40)).join(' · ');
  detail.innerHTML = `<span class="dim">${esc(day)}</span> ${count}条${top5 ? ` · ${top5}` : ''}`;
}
```

- [ ] **Step 4: 更新 `load()` 函数中的 Promise.all，改为请求 60 天事件并追加新 API**

找到：
```javascript
  const [stats, events, summary, insights] = await Promise.all([
    fetch('/api/stats').then(r=>r.json()).catch(()=>({})),
    fetch('/api/events?days=1').then(r=>r.json()).catch(()=>[]),
    fetch('/api/summary').then(r=>r.json()).catch(()=>({})),
    fetch('/api/insights').then(r=>r.json()).catch(()=>({})),
  ]);
```

替换为：

```javascript
  const [stats, events, summary, insights, profileAnalysis, summaries] = await Promise.all([
    fetch('/api/stats').then(r=>r.json()).catch(()=>({})),
    fetch('/api/events?days=60').then(r=>r.json()).catch(()=>[]),
    fetch('/api/summary').then(r=>r.json()).catch(()=>({})),
    fetch('/api/insights').then(r=>r.json()).catch(()=>({})),
    fetch('/api/profile-analysis').then(r=>r.json()).catch(()=>({})),
    fetch('/api/summaries').then(r=>r.json()).catch(()=>[]),
  ]);
  _eventsCache = events;
```

- [ ] **Step 5: 在 `load()` 中 `// Deep insights` 渲染之后追加模块 1-4 渲染调用**

```javascript
  // Profile basic
  document.getElementById('profile-basic').innerHTML = renderProfileBasic(summary.profile || {});

  // Deep profile analysis
  document.getElementById('profile-analysis').innerHTML = renderProfileAnalysis(profileAnalysis);
  if (profileAnalysis?.generated_at) {
    const ts = new Date(profileAnalysis.generated_at).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
    const typeLabel = profileAnalysis.type === 'daily' ? '晨报' : '定期';
    // type-badge class name is static; ts and typeLabel are safe strings
    document.getElementById('analysis-meta').innerHTML =
      `<span class="type-badge">${esc(typeLabel)}</span>${esc(ts)}`;
  }

  // 7-day trend
  document.getElementById('trend-list').innerHTML = renderTrend(summaries);

  // Heatmap (separate fetch since it's an aggregation endpoint)
  fetch('/api/events/heatmap?days=60').then(r => r.json()).then(renderHeatmap).catch(() => {});
```

- [ ] **Step 6: 在 `// ── Tasks panel` 注释之前追加 refreshAnalysis 函数**

```javascript
// ── Profile analysis refresh ─────────────────────────────────
async function refreshAnalysis() {
  const btn = document.getElementById('btn-refresh-analysis');
  btn.disabled = true;
  btn.textContent = '生成中...';
  try {
    await fetch('/api/profile-analysis/refresh', { method: 'POST' });
    // Result arrives via WebSocket profile_analysis_done / profile_analysis_error
  } catch {
    btn.disabled = false;
    btn.textContent = '刷新';
  }
}
```

- [ ] **Step 7: 替换 `ws.onmessage` 处理器，加入画像通知响应**

找到：
```javascript
ws.onmessage = () => { load(); loadTasks(); };
```

替换为：

```javascript
ws.onmessage = (evt) => {
  try {
    const msg = JSON.parse(evt.data);
    if (msg.type === 'profile_analysis_done') {
      const btn = document.getElementById('btn-refresh-analysis');
      btn.disabled = false;
      btn.textContent = '刷新';
      fetch('/api/profile-analysis').then(r => r.json()).then(d => {
        // d comes from our own API — all fields through esc() in renderProfileAnalysis
        document.getElementById('profile-analysis').innerHTML = renderProfileAnalysis(d);
        if (d?.generated_at) {
          const ts = new Date(d.generated_at).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
          document.getElementById('analysis-meta').innerHTML =
            `<span class="type-badge">${esc(d.type === 'daily' ? '晨报' : '定期')}</span>${esc(ts)}`;
        }
      });
      return;
    }
    if (msg.type === 'profile_analysis_error') {
      const btn = document.getElementById('btn-refresh-analysis');
      btn.disabled = false;
      // error message from our own server — esc() as precaution
      btn.textContent = `失败: ${esc(msg.error || '重试')}`;
      return;
    }
  } catch {}
  load();
  loadTasks();
};
```

- [ ] **Step 8: 提交**

```bash
git add dashboard/public/index.html
git commit -m "feat: add profile cards, trend summary and heatmap modules to dashboard"
```

---

### Task 8: index.html — 模块 5-7（分类统计 + 任务统计 + 搜索）

**Files:**
- Modify: `dashboard/public/index.html`

- [ ] **Step 1: 在 `<!-- 7-Day Trend Summary -->` 之前插入模块 5（分类时间分布）骨架**

```html
  <!-- Category Time Distribution -->
  <div class="card" id="category-card">
    <h2>分类时间分布</h2>
    <div class="cat-toggle">
      <button class="cat-btn active" onclick="loadCategories(1, this)">今日</button>
      <button class="cat-btn" onclick="loadCategories(7, this)">7 天</button>
      <button class="cat-btn" onclick="loadCategories(30, this)">30 天</button>
    </div>
    <div id="category-list"><div class="no-data">加载中...</div></div>
  </div>
```

- [ ] **Step 2: 在任务列表 `id="tasks-list"` 之前插入模块 6（任务统计条）**

找到：
```html
    <div id="tasks-list"><span class="no-data">暂无任务</span></div>
```

在其之前插入：
```html
    <div id="task-stats-bar" class="task-stats-bar"></div>
```

- [ ] **Step 3: 替换最近活动卡片，加入模块 7（搜索栏）**

找到：
```html
  <div class="card">
    <h2>最近活动（24h）</h2>
    <div id="events"></div>
  </div>
```

替换为：
```html
  <div class="card">
    <h2>最近活动</h2>
    <div class="event-search-bar">
      <input class="event-search-input" id="event-search" placeholder="搜索标题..." oninput="filterEvents()">
      <select class="event-src-select" id="event-src-filter" onchange="filterEvents()">
        <option value="">全部来源</option>
      </select>
    </div>
    <div id="events"></div>
  </div>
```

- [ ] **Step 4: 在 `showHeatmapDay` 函数之后追加模块 5、6、7 函数**

```javascript
// ── Module 5: Category Stats ─────────────────────────────────
// category names from DB go through esc()
const CAT_COLORS = ['#3a5a4a','#4a4a6a','#5a4a3a','#3a4a5a','#4a5a3a','#5a3a4a','#4a3a5a'];

async function loadCategories(days, btn) {
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  try {
    const rows = await fetch(`/api/stats/categories?days=${days}`).then(r => r.json());
    const el = document.getElementById('category-list');
    if (!rows.length) { el.innerHTML = '<div class="no-data">暂无数据</div>'; return; }
    const maxMin = Math.max(...rows.map(r => r.total_min || 0), 1);
    // category names go through esc(); numeric values are safe to use directly
    el.innerHTML = rows.map((r, i) => `
      <div class="cat-bar-row">
        <span class="cat-bar-label">${esc(r.category || '未分类')}</span>
        <div class="cat-bar-track">
          <div class="cat-bar-fill" style="width:${((r.total_min||0)/maxMin*100).toFixed(1)}%;background:${CAT_COLORS[i % CAT_COLORS.length]}"></div>
        </div>
        <span class="cat-bar-val">${Math.round(r.total_min || 0)}m</span>
      </div>`).join('');
  } catch {}
}

// ── Module 6: Task Stats ─────────────────────────────────────
// All values are computed numbers — safe to use directly
function renderTaskStats(tasks) {
  if (!tasks?.length) { document.getElementById('task-stats-bar').innerHTML = ''; return; }
  const done = tasks.filter(t => t.status === 'done').length;
  const failed = tasks.filter(t => t.status === 'failed').length;
  const pending = tasks.filter(t => ['pending','awaiting_approval'].includes(t.status)).length;
  const durations = tasks
    .filter(t => t.started_at && t.finished_at)
    .map(t => (new Date(t.finished_at) - new Date(t.started_at)) / 1000);
  const avgSec = durations.length
    ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
    : 0;
  const avgStr = avgSec >= 60
    ? `${Math.floor(avgSec / 60)}分${avgSec % 60}秒`
    : `${avgSec}秒`;
  const items = [
    ['总计', tasks.length],
    ['完成', done],
    ['失败', failed],
    ['待执行', pending],
    ['均用时', avgSec ? avgStr : '—'],
  ];
  document.getElementById('task-stats-bar').innerHTML =
    items.map(([l, v]) =>
      `<div class="task-stat-item"><span class="task-stat-num">${v}</span>${esc(l)}</div>`
    ).join('');
}

// ── Module 7: Event Search ───────────────────────────────────
// source names from DB go through esc(); event titles go through esc()
function buildSourceOptions() {
  const sel = document.getElementById('event-src-filter');
  if (!sel) return;
  const sources = [...new Set(_eventsCache.map(e => e.source).filter(Boolean))].sort();
  const existing = [...sel.options].map(o => o.value);
  sources.forEach(src => {
    if (!existing.includes(src)) {
      const opt = document.createElement('option');
      opt.value = src;
      opt.textContent = src; // textContent — no XSS risk
      sel.appendChild(opt);
    }
  });
}

function filterEvents() {
  const q = (document.getElementById('event-search')?.value || '').toLowerCase();
  const src = document.getElementById('event-src-filter')?.value || '';
  const filtered = _eventsCache.filter(e =>
    (!q || (e.title || '').toLowerCase().includes(q)) &&
    (!src || e.source === src)
  );
  // event titles and source go through esc()
  document.getElementById('events').innerHTML =
    filtered.slice(0, 25).map(e =>
      `<div class="row">
        <span><span class="src-badge">${esc(e.source)}</span>${esc((e.title||'').slice(0,38))}</span>
        <span class="dim">${Math.round(e.duration_minutes||0)}m</span>
      </div>`
    ).join('') || '<div class="no-data">暂无数据</div>';
}
```

- [ ] **Step 5: 在 `load()` 的 `// Events` 渲染部分替换为调用 filterEvents**

找到：
```javascript
  // Events
  const ev = document.getElementById('events');
  ev.innerHTML = events.slice(0,25).map(e=>
    `<div class="row">
      <span><span class="src-badge">${e.source}</span>${(e.title||'').slice(0,38)}</span>
      <span class="dim">${Math.round(e.duration_minutes||0)}m</span>
    </div>`
  ).join('') || '<div class="no-data">暂无数据</div>';
```

替换为：

```javascript
  // Events (with search filter)
  buildSourceOptions();
  filterEvents();
```

- [ ] **Step 6: 在 `loadTasks()` 的 `el.innerHTML = tasks.map(taskCardHtml).join('')` 之后追加**

```javascript
    renderTaskStats(tasks);
```

- [ ] **Step 7: 在 `setInterval(load, 60000)` 之后追加分类统计初始加载**

```javascript
loadCategories(1, document.querySelector('.cat-btn'));
```

- [ ] **Step 8: 最终手动验证**

在浏览器打开 `http://localhost:23714`，逐一检查：

```
✓ 用户画像卡片出现（无数据时显示"等待首次分析"）
✓ 深度画像分析卡片出现，刷新按钮可点击，点击后按钮变为"生成中..."
✓ 7日趋势卡片出现
✓ 热力图卡片出现，格子可点击并显示当日详情
✓ 分类时间分布卡片出现，今日/7天/30天按钮切换正常
✓ 任务面板上方出现统计数字条
✓ 最近活动卡片有搜索框，实时过滤有效
✓ 控制台无 JS 错误
```

- [ ] **Step 9: 提交**

```bash
git add dashboard/public/index.html
git commit -m "feat: add category stats, task stats bar and event search to dashboard"
```

---

## 收尾

- [ ] **运行完整测试**

```bash
python -m pytest tests/test_events_db.py -v
```

预期：全部 PASSED

- [ ] **最终提交（如有零散改动）**

```bash
git status
git add -p
git commit -m "chore: dashboard v2 final cleanup"
```
