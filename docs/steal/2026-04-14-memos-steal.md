# R53 — Memos Steal Report

**Source**: https://github.com/usememos/memos | **Stars**: 58,840 | **License**: MIT
**Date**: 2026-04-14 | **Category**: Memory/Storage — Self-hosted note system with MCP integration

---

## TL;DR

Memos 是一个 Go+React 轻量级笔记系统。核心亮点三条：

1. **CEL 查询引擎** — 用 Google CEL 编译过滤表达式，生成 dialect-agnostic SQL，frontend 直接拼 CEL 字符串发给后端。Orchestrator 的记忆查询目前是文件遍历，这个思路可以直接借。
2. **Payload-as-JSON 附加字段** — memo 表只有核心列，扩展字段（tags、属性、位置）塞进 `payload TEXT` 列存 protobuf JSON，CEL 引擎通过 `FieldKindJSONList`/`FieldKindJSONBool` 透明查询 JSON 内嵌路径。新增字段不改 schema。
3. **原生 MCP Server** — 把整个笔记系统暴露为 MCP tools/resources/prompts，任何 AI agent 可以 `create_memo`、`search_memos`、`list_tags`，memo 以 `memo://memos/{uid}` URI 作为 resource 被读取，返回带 YAML frontmatter 的 Markdown。

---

## Architecture Overview

```
cmd/
  └── main.go
server/
  ├── router/api/v1/     ← gRPC-connect HTTP API (protobuf)
  ├── router/mcp/        ← MCP server (mark3labs/mcp-go)
  ├── router/rss/        ← RSS feed
  └── runner/memopayload/← 后台 runner：批量重建 payload
store/
  ├── driver.go          ← Driver interface (SQLite/MySQL/Postgres)
  ├── db/sqlite|mysql|postgres/  ← SQL 实现
  ├── migration/         ← embed FS 管理版本迁移
  ├── cache/             ← TTL + MaxItems in-memory cache
  └── memo.go            ← 核心 Memo struct + CRUD
internal/
  ├── filter/            ← CEL engine → SQL renderer
  ├── markdown/          ← goldmark AST：ExtractAll() 单次 parse
  └── ai/                ← OpenAI/Gemini provider 接口（仅音频转录）
web/src/
  ├── hooks/useMemoFilters.ts  ← 前端拼 CEL 字符串
  └── contexts/MemoFilterContext  ← 全局过滤状态
```

**数据流**：

```
前端过滤 UI
  → useMemoFilters() 拼 CEL 字符串
  → API: filter=["content.contains(\"foo\")", "tag in [\"work\"]"]
  → filter.AppendConditions() 编译 CEL → Condition tree
  → renderer.Render() → SQL WHERE fragment + args
  → SQLite/MySQL/Postgres 查询
```

---

## Steal Sheet

### P0 — CEL 查询引擎（直接可偷）

**问题**：Orchestrator 的记忆检索现在是全文件遍历 + 字符串匹配，没有结构化查询。

**Memos 实现**：

```go
// internal/filter/schema.go
// 每个字段声明 kind（scalar/json_bool/json_list）、backing column、dialect 表达式
fields := map[string]Field{
    "tags": {
        Kind:     FieldKindJSONList,
        Type:     FieldTypeString,
        Column:   Column{Table: "memo", Name: "payload"},
        JSONPath: []string{"tags"},
    },
    "has_task_list": {
        Kind:     FieldKindJSONBool,
        JSONPath: []string{"property", "hasTaskList"},
    },
    "created_ts": {
        Kind: FieldKindScalar,
        Expressions: map[DialectName]string{
            DialectMySQL: "UNIX_TIMESTAMP(%s)",
        },
    },
}

// 使用：一行编译 + 渲染
stmt, err := engine.CompileToStatement(ctx,
    `tag in ["work"] && created_ts >= now() - 86400`,
    filter.RenderOptions{Dialect: filter.DialectSQLite},
)
// → SQL: `memo`.`payload` JSON contains 'work' AND `memo`.`created_ts` >= ?
```

**对比 Orchestrator**：
- Orchestrator 的 `.remember/` 是 YAML frontmatter 文件，查询走 Python 正则
- 引入 SQLite + CEL 后，可用 `tag in ["R53"]`、`created_ts >= now()-7*86400`、`content.contains("wake")`
- CEL schema 声明式，新增字段不改查询逻辑

**可行性**：CEL 库 `google/cel-go` 纯 Go，MIT。filter/ 目录约 600 行，完全独立可移植。

---

### P0 — Payload-as-JSON 模式（扩展字段零 schema 锁定）

**问题**：Orchestrator memory 文件的 frontmatter 字段经常因为新需求扩展，每次都要改解析逻辑。

**Memos 实现**：

```sql
-- LATEST.sql
CREATE TABLE memo (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid TEXT NOT NULL UNIQUE,
  content TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL DEFAULT 'PRIVATE',
  pinned INTEGER NOT NULL DEFAULT 0,
  payload TEXT NOT NULL DEFAULT '{}'   -- ← 所有扩展字段在这里
);
```

```proto
// store/memo.proto
message MemoPayload {
  Property property = 1;    // has_link, has_task_list, has_code, title
  Location location = 2;    // lat/lng
  repeated string tags = 3; // 标签数组
}
```

迁移时只需更新 protobuf 定义 + CEL schema，SQL 表结构不动。Payload 由后台 runner `memopayload.RunOnce()` 批量重建（全量扫描 content，单次 goldmark parse 提取所有字段）。

**可迁移到 Orchestrator**：将 `core-memories.md` 中的 entries 改为 SQLite 行，`payload` 列存 JSON（tags、evidence tier、链接的 round 号、来源类型），CEL 查询代替手写 grep。

---

### P1 — MCP Server 暴露记忆层

**Memos 已经做了**：

```go
// server/router/mcp/mcp.go
mcpSrv := mcpserver.NewMCPServer("Memos", "1.0.0",
    mcpserver.WithToolCapabilities(true),
    mcpserver.WithResourceCapabilities(true, true),
    mcpserver.WithPromptCapabilities(true),
)
// tools: create_memo, search_memos, list_memos, update_memo, delete_memo
// resources: memo://memos/{uid} → YAML frontmatter + Markdown body
// prompts: capture, review, daily_digest
```

Resource 格式是带 YAML frontmatter 的 Markdown，和 Orchestrator 现有 `.remember/` 文件格式完全对齐：

```markdown
---
name: memos/abc123
creator: users/admin
visibility: PRIVATE
tags: [R53, steal, memory]
create_time: 1744588800
---

实际 memo 内容...
```

**偷师点**：Orchestrator 的 `SOUL/private/` 完全可以通过同样的 MCP server 暴露，让 agent 用 `list_memos`/`search_memos` 检索记忆，而不是靠 Claude Code 读文件。

---

### P1 — 单次 AST Walk ExtractAll()

**问题**：如果分别提取 tags、properties、mentions 需要 parse 3 次。

**Memos 实现**：

```go
// internal/markdown/markdown.go
func (s *service) ExtractAll(content []byte) (*ExtractedData, error) {
    root, err := s.parse(content)  // 只 parse 一次
    // 一次 Walk 同时收集 tags、mentions、property
    err = gast.Walk(root, func(n gast.Node, entering bool) (gast.WalkStatus, error) {
        if tagNode, ok := n.(*mast.TagNode); ok {
            data.Tags = append(data.Tags, string(tagNode.Tag))
        }
        if mentionNode, ok := n.(*mast.MentionNode); ok {
            data.Mentions = append(...)
        }
        // has_link, has_code, has_task_list...
        return gast.WalkContinue, nil
    })
    return data, nil
}
```

**对应 Orchestrator**：SOUL/private/ 的 YAML frontmatter 解析 + 内容提取也可以合并为一次 pass。

---

### P2 — 双 ID 系统（系统 ID vs 用户 UID）

```go
type Memo struct {
    ID  int32  // 系统自增 ID，内部关联用
    UID string // 用户可见的 shortuuid，URL 里出现的是这个
}
```

Orchestrator 的 memory 文件名就是 UID，可以在 SQLite 里保留文件名作为 UID，系统 ID 用于关联（比如 `experience` 关联到某个 `memory`）。

---

### P2 — 关系类型枚举（REFERENCE vs COMMENT）

```go
// store/memo_relation.go
type MemoRelationType string
const (
    MemoRelationReference MemoRelationType = "REFERENCE"
    MemoRelationComment   MemoRelationType = "COMMENT"
)
```

Orchestrator 的记忆之间也有隐含关系（experience 引用 memory，round 引用 pattern），但目前是文件路径字符串引用，没有结构化。借鉴这个枚举可以建图。

---

### P3 — 行软删除（RowStatus NORMAL/ARCHIVED）

```sql
row_status TEXT NOT NULL CHECK (row_status IN ('NORMAL', 'ARCHIVED')) DEFAULT 'NORMAL'
```

对应 CLAUDE.md 里的"删除 = 移到 .trash/"原则。Orchestrator 可以在 SQLite 里用 `row_status=ARCHIVED` 代替物理 mv，保留可查询性。

---

## Comparison Matrix

| 维度 | Memos | Orchestrator 当前状态 |
|------|-------|----------------------|
| 存储后端 | SQLite/MySQL/Postgres（用户选择） | YAML 文件（.remember/ + SOUL/private/） |
| 查询机制 | CEL → SQL（结构化，支持复合条件） | 文件遍历 + grep/正则 |
| 标签系统 | `payload.tags[]` 存 JSON，CEL `tag in [...]` 查询 | frontmatter `tags:` 字段，手动过滤 |
| 记忆关系 | memo_relation 表（REFERENCE/COMMENT 枚举） | 文件路径字符串引用 |
| 内容解析 | goldmark GFM，单次 ExtractAll() | 无统一 parser（各处手写正则） |
| AI 集成 | OpenAI/Gemini 音频转录；无自动分类 | Claude 全程参与写/读 |
| MCP 暴露 | 完整 MCP server（tools+resources+prompts） | 无 |
| 缓存层 | in-memory TTL cache（用户/设置级别） | 无 |
| 可见性控制 | PUBLIC/PROTECTED/PRIVATE 三级 | 无（全部 private 文件） |
| schema 演进 | payload JSON 列 + protobuf 版本化 | 手动编辑 YAML |

---

## Gaps

1. **Memos 没有 AI 自动分类**：tags 完全手动，AI 只做音频转录。Orchestrator 的记忆是 Claude 自己写的，质量更高但不可批量重建。

2. **Memos 没有 evidence tier**：R42 引入的 `verbatim/artifact/impression` 分级在 Memos 里没有对应概念，payload 里只有结构属性，没有置信度。

3. **Memos 的 MCP 是只读 resource + 读写 tool 混合**：`memo://memos/{uid}` 是 resource（只读），但 `create_memo`/`update_memo` 是 tool（读写）。Orchestrator 如果暴露 MCP，需要严格控制 tool 的写权限（不能让 agent 随意修改 core-memories）。

4. **Memos 没有记忆老化/重要性衰减**：所有 memo 平等，没有 LRU 或重要性打分。Orchestrator 的 experiences.jsonl 有时间戳但也没有衰减。

5. **Memos 无全文搜索索引**：`content.contains("foo")` 在 SQLite 里走全表 LIKE，大量数据时性能差。没有 FTS5。可以加 `CREATE VIRTUAL TABLE memo_fts USING fts5(content)`。

---

## Adjacent Discoveries

### SSE 实时推送
`server/router/api/v1/sse_handler.go` — memo 创建后广播 SSE 事件给所有连接的前端。Orchestrator 的 Telegram bot 如果有 channel 消息也可以用类似推送通知机制。

### Shortcut 系统（保存的搜索）
```go
// proto: Shortcut { name, filter, visibility, pinned }
```
用户可以保存一个 CEL filter 字符串为命名 shortcut（"最近一周的 work 标签"），前端用 shortcut 替代手动构造 filter。对应 Orchestrator 可以预定义记忆查询模板。

### 版本迁移用 embed.FS + semver 排序
```go
//go:embed migration
var migrationFS embed.FS
```
所有 SQL migration 文件 embed 进二进制，启动时按 semver 排序应用，不依赖外部工具。Orchestrator 如果引入 SQLite，可以照抄这个模式。

### memo_share：带过期时间的临时分享链接
```sql
CREATE TABLE memo_share (
  uid TEXT NOT NULL UNIQUE,
  memo_id INTEGER NOT NULL,
  expires_ts BIGINT DEFAULT NULL,  -- NULL = 永不过期
  FOREIGN KEY (memo_id) REFERENCES memo(id) ON DELETE CASCADE
);
```
对应 Orchestrator：可以给 agent 生成临时读取某个 private memory 的 token，过期后自动失效。

---

## Meta Insights

1. **CEL 是 schema-aware query language 的正确抽象**：CEL 比 SQL 字符串拼接安全，比 ORM 灵活，比自定义 DSL 省力。Orchestrator 应该认真评估引入 `google/cel-go`，而不是继续用字符串 grep。

2. **"payload as JSON + protobuf schema"比 YAML frontmatter 扩展性强得多**：YAML frontmatter 每次加字段都要改 parser，JSON payload 只改 proto 定义，查询层（CEL schema）同步更新即可。这是 Memos 最值得直接复制的架构决策。

3. **MCP server 是记忆层的正确暴露方式**：让 AI agent 通过 MCP tools 操作记忆（而不是直接读文件），可以加访问控制、审计日志、rate limiting。Orchestrator 现在让 Claude Code 直接读写 SOUL/private/，这层控制完全缺失。

4. **tag 从 content 自动提取 vs 手动声明**：Memos 选择从 markdown `#tag` 语法自动提取，存入 payload。Orchestrator 的 evidence tier、memory type 等元数据是手动写 frontmatter——两种方式各有适用场景，关键信息不应该依赖自动提取。

5. **58k stars 的项目仍然只有 SQLite 全表 LIKE 做全文搜索**：说明 FTS 对大多数个人场景不是刚需。Orchestrator 的记忆量更少，文件遍历在当前规模是够的，引入 CEL+SQLite 的价值在于查询表达力，不在于性能。
