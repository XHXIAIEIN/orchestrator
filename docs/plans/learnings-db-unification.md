# Plan: Learnings DB 统一 — 文件→DB，针对模型优化

## Context

当前 learnings 数据分裂在两个系统：
- `.learnings/*.md` — Clawvard 考试产出，11 条，带丰富证据链（Detail、validation、counter-evidence、交叉引用）
- `events.db learnings 表` — 旧 pipeline 手写，8 条，context 字段大多为空

两套数据不重叠、不同步。compiler 刚改为从 `.learnings/` 解析 markdown 生成 context pack，但这是过渡方案。

目标：**DB 是唯一数据源**，`.learnings/` 文件废弃。所有读写都走 DB。针对模型检索优化，不需要人类可读格式。

## DB Schema 扩展

`learnings` 表新增/修改字段：

```sql
ALTER TABLE learnings ADD COLUMN detail TEXT DEFAULT '';
-- 多段证据文本（validation evidence, regression evidence, counter-evidence）
-- 不需要结构化，模型直接读纯文本

ALTER TABLE learnings ADD COLUMN related_keys TEXT DEFAULT '';
-- JSON array: ["agent-output-budget"]
-- ERR↔LRN 交叉引用，用 pattern_key 关联

ALTER TABLE learnings ADD COLUMN entry_type TEXT DEFAULT 'learning';
-- 'error' | 'learning' | 'feature'
-- 当前表只有 source_type 区分来源，没区分 ERR/LRN/FTR 三分类

ALTER TABLE learnings ADD COLUMN first_seen TEXT DEFAULT '';
-- 首次出现时间（当前只有 created_at，但 recurrence bump 不更新它）

ALTER TABLE learnings ADD COLUMN last_seen TEXT DEFAULT '';
-- 最近出现时间（当前无此字段，recurrence bump 后无法知道最近一次是什么时候）
```

不需要的字段：`source_type`（被 `entry_type` 替代）、`ttl_days`/`expires_at`（从未使用，可保留但不管）。

## 数据迁移

一次性脚本 `SOUL/tools/migrate_learnings.py`：

1. 解析 `.learnings/ERRORS.md` 和 `.learnings/LEARNINGS.md`（复用 `_parse_learnings_file()`）
2. 对每条：
   - 用 `pattern_key` 查 DB，存在则 UPDATE（填入 detail、related_keys、调整 recurrence/status）
   - 不存在则 INSERT
3. entry_type 根据 ID 前缀映射：ERR→error, LRN→learning, FTR→feature
4. related_keys 根据命名惯例推导：`agent-output-budget-fix` → relates to `agent-output-budget`
5. 迁移完成后，`.learnings/` 目录 mv 到 `.trash/learnings-migrated/`

## Pipeline 改写

### 1. `src/governance/audit/learnings.py` — 写入目标从文件切到 DB

当前：`append_error()` / `append_learning()` → 解析 markdown → 写回文件

改为：
```python
def append_error(pattern_key, summary, detail, area, db: EventsDB):
    return db.add_learning(
        pattern_key=pattern_key,
        rule=summary,
        detail=detail,        # 新字段，完整证据
        area=area,
        entry_type='error',
    )

def append_learning(pattern_key, summary, detail, area, db: EventsDB):
    return db.add_learning(
        pattern_key=pattern_key,
        rule=summary,
        detail=detail,
        area=area,
        entry_type='learning',
        related_keys=_infer_related_keys(pattern_key),  # 自动推导交叉引用
    )
```

不再需要：`_parse_entries()`、`_format_entry()`、`_append_to_file()`、`_next_id()`、`get_pattern_occurrences()`。
保留：`get_promotable_entries()` — 改为查 DB。
保留：`check_blast_radius()` — 不涉及 learnings。

### 2. `src/storage/_learnings_mixin.py` — 扩展 DB 方法

`add_learning()` 改动：
- 接受 `detail`, `related_keys`, `entry_type`, `first_seen`, `last_seen` 参数
- recurrence bump 时同时更新 `last_seen` 和追加 `detail`（新证据 append 到旧 detail 后面，用 `\n---\n` 分隔）

新增方法：
```python
def get_learnings_for_compilation(self, entry_type=None, status=None) -> list[dict]:
    """compiler 用：返回完整 learnings 含 detail 和 related_keys"""

def get_learnings_summary(self) -> dict:
    """快速概览：按 entry_type 分组计数 + 最高 recurrence 的 top 5"""
```

### 3. `src/governance/audit/promoter.py` — 简化

当前：解析 markdown 文件 → 写入 boot.md 文本 → 标记文件中的 status

改为：
- `scan_and_promote()` 查 DB `WHERE recurrence >= threshold AND status = 'pending'`
- `promote_to_boot()` 不变（仍然写 boot.md 文本）
- `mark_as_promoted()` 改为 `db.promote_learning(id)`

不再需要导入 `_parse_entries`。

### 4. `src/governance/audit/self_eval.py` — 调用方改适配

当前调用 `learnings.append_error(... file_path=...)` 传文件路径。
改为传 `db` 实例。检查 `ingest_exam()` 的签名和调用链。

### 5. `SOUL/tools/compiler.py` — context pack 从 DB 读

`compile_learnings_pack()` 当前解析 `.learnings/` markdown 文件。

改为：
```python
def compile_learnings_pack(output_dir: Path, db_path=None) -> Path:
    db = EventsDB(db_path or default_db_path)
    errors = db.get_learnings_for_compilation(entry_type='error')
    learnings = db.get_learnings_for_compilation(entry_type='learning')
    # 格式化输出（同当前逻辑，只是数据源变了）
```

删除 `_parse_learnings_file()` 函数。

`promoted_learnings()` 已经从 DB 读，不需要改。

## 文件清理

- `.learnings/` → `.trash/learnings-migrated/`（迁移后）
- `src/governance/audit/learnings.py` — 大幅精简，删除所有文件解析逻辑
- compiler.py 删除 `_parse_learnings_file()` 和 `LEARNINGS_DIR` 常量

## 验证

1. `python SOUL/tools/migrate_learnings.py` — 迁移完成，DB learnings 表有 ~15 条（合并后去重）
2. `python -c "from src.storage.events_db import EventsDB; db=EventsDB('data/events.db'); print(db.get_learnings_for_compilation())"` — 返回完整数据含 detail
3. `python SOUL/tools/compiler.py` — context pack 从 DB 生成，内容与迁移前一致
4. 跑一次 Clawvard exam → 确认新 ERR/LRN 写入 DB 而非文件
5. `.learnings/` 目录不存在（已移到 .trash/）

## 关键文件

| 文件 | 动作 |
|------|------|
| `src/storage/_learnings_mixin.py` | 扩展 schema + 新方法 |
| `src/governance/audit/learnings.py` | 重写：文件操作 → DB 操作 |
| `src/governance/audit/promoter.py` | 简化：去掉文件解析依赖 |
| `src/governance/audit/self_eval.py` | 适配：传 db 替代 file_path |
| `SOUL/tools/compiler.py` | 改 learnings pack 数据源 |
| `SOUL/tools/migrate_learnings.py` | 新增：一次性迁移脚本 |
