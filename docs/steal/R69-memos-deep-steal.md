---
title: "R69 — Memos Deep Steal：存储层 & 搜索引擎"
date: 2026-04-14
source: https://github.com/usememos/memos
clone: D:/Agent/.steal/memos/
branch: steal/round-deep-rescan-r60
type: specific-module
dimensions:
  deep: [Memory/Learning, Quality/Review]
  brief: [Security, Execution, Context, Failure]
previous: 2026-04-14-memos-steal.md  # R53 浅析
---

# R69 — Memos 深度偷师：存储层 & 搜索引擎

> 上次（R53）只扫了 README 和目录结构。这次进源码。
> 聚焦两个维度：**Memory/Learning**（存储如何组织 + 检索知识）、**Quality/Review**（工程质量标准）。

---

## 一、架构鸟瞰（速查）

```
proto/store/memo.proto          ← MemoPayload protobuf schema
store/
  driver.go                     ← Driver interface（所有 DB 操作抽象）
  store.go                      ← Store struct + 三个内存 cache
  memo.go                       ← 业务层 Memo CRUD（+删除时级联清理）
  migrator.go                   ← 版本化迁移系统（embed FS + 事务）
  db/sqlite/memo.go             ← SQLite 具体实现（动态 SQL 拼接）
  db/sqlite/functions.go        ← 注册 memos_unicode_lower 自定义函数
  cache/cache.go                ← 带 TTL 的并发安全内存 cache
internal/filter/
  schema.go                     ← CEL 变量声明 + Field 元数据
  engine.go                     ← CEL 编译 → IR（Program）
  parser.go                     ← CEL AST → 条件树（IR）
  render.go                     ← 条件树 → 方言 SQL + 参数
  helpers.go                    ← AppendConditions（调用入口）
server/runner/memopayload/      ← 异步全量重建 payload（batch=100）
internal/webhook/
  validate.go                   ← SSRF 防护（保留 CIDR 白名单）
  webhook.go                    ← safeDialContext + PostAsync
```

---

## 二、深度维度 1：Memory/Learning（存储 & 检索）

### 2.1 存储模型：五个深度层

**Layer 1 — Schema 设计**

```sql
-- store/migration/sqlite/LATEST.sql
CREATE TABLE memo (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  uid         TEXT NOT NULL UNIQUE,          -- 用户可自定义的稳定标识符
  creator_id  INTEGER NOT NULL,
  created_ts  BIGINT NOT NULL DEFAULT (strftime('%s', 'now')),
  updated_ts  BIGINT NOT NULL DEFAULT (strftime('%s', 'now')),
  row_status  TEXT NOT NULL CHECK (row_status IN ('NORMAL', 'ARCHIVED')) DEFAULT 'NORMAL',
  content     TEXT NOT NULL DEFAULT '',
  visibility  TEXT NOT NULL CHECK (visibility IN ('PUBLIC', 'PROTECTED', 'PRIVATE')) DEFAULT 'PRIVATE',
  pinned      INTEGER NOT NULL CHECK (pinned IN (0, 1)) DEFAULT 0,
  payload     TEXT NOT NULL DEFAULT '{}'    -- JSON blob：tags + property + location
);
```

关键设计决策：
- `uid` 与 `id` 双轨：`id` 是内部整数主键（JOIN 性能），`uid` 是用户侧稳定标识（URL、API）。两者分离，换 ID 生成策略不破坏 URL。
- `payload` JSON blob：标签、boolean 属性（hasLink/hasCode/hasTaskList）、地理位置全塞进一个 TEXT 列，避免 schema 频繁迁移。新增属性 = 修改 proto，无需改表结构。
- `row_status` 软删除：归档不删行，CHECK 约束保证值域。

**Layer 2 — payload 结构（protobuf 定义）**

```protobuf
// proto/store/memo.proto
message MemoPayload {
  Property property = 1;
  Location location = 2;
  repeated string tags = 3;

  message Property {
    bool has_link             = 1;
    bool has_task_list        = 2;
    bool has_code             = 3;
    bool has_incomplete_tasks = 4;
    string title              = 5;  // 从第一个 H1 提取
  }
  message Location {
    string placeholder = 1;
    double latitude    = 2;
    double longitude   = 3;
  }
}
```

payload 在数据库里存 protojson 字符串，读出后用 `protojsonUnmarshaler.Unmarshal` 反序列化。protobuf 提供 schema 验证，JSON 提供灵活性——两者都要。

**Layer 3 — payload 的生命周期：同步写 + 异步重建**

创建/更新 memo 时：
```go
// server/runner/memopayload/runner.go
func RebuildMemoPayload(ctx context.Context, memo *store.Memo, markdownService markdown.Service) error {
    data, err := markdownService.ExtractAll([]byte(memo.Content))
    // 一次 parse 提取 tags + properties
    memo.Payload.Tags = data.Tags
    memo.Payload.Property = data.Property
}
```

启动时异步批量重建（应对 schema 升级后 payload 失效）：
```go
// RunOnce：batchSize=100，offset 游标分页，避免全表加载内存
for {
    memos, _ := r.Store.ListMemos(ctx, &store.FindMemo{Limit: &limit, Offset: &offset})
    if len(memos) == 0 { break }
    // 逐条 RebuildMemoPayload → UpdateMemo
    offset += len(memos)
}
```

**偷师点**：分离"写时计算"（同步 RebuildMemoPayload）与"启动时修复"（RunOnce 批量重建）。迁移时不需要写复杂的迁移 SQL，直接重跑 Go 函数即可。

**Layer 4 — 查询层：动态条件树**

```go
// store/db/sqlite/memo.go — ListMemos 动态 SQL
where, args := []string{"1 = 1"}, []any{}
// CEL 过滤器先走 filter.AppendConditions
filter.AppendConditions(ctx, engine, find.Filters, filter.DialectSQLite, &where, &args)
// 常规条件追加
if v := find.ID; v != nil {
    where, args = append(where, "`memo`.`id` = ?"), append(args, *v)
}
// ...
query := "SELECT ... FROM `memo` ... WHERE " + strings.Join(where, " AND ") +
         " ORDER BY " + strings.Join(orderBy, ", ")
```

`1 = 1` 开头保证 `strings.Join(where, " AND ")` 永远合法，不需要特判第一个条件。

**Layer 5 — CEL 过滤器：类型安全查询**

用户传 `filter = 'tag in ["work"] && created_ts > now() - 86400'`，系统把它编译成 SQL：

```
filter.AppendConditions
  → engine.CompileToStatement(filterStr, dialect)
  → cel.Compile → AST
  → buildCondition(AST, schema) → 条件树（IR）
  → renderer.Render → Statement{SQL, Args}
```

最终产物是参数化 SQL，完全消除 SQL 注入风险。

### 2.2 搜索实现：CJK 支持的关键

**问题**：SQLite 的 `LOWER()` 只处理 ASCII，中文 `LIKE` 不区分大小写会失效。

**解法**：注册自定义标量函数 `memos_unicode_lower`：

```go
// store/db/sqlite/functions.go
func ensureUnicodeLowerRegistered() error {
    registerUnicodeLowerOnce.Do(func() {
        registerUnicodeLowerErr = msqlite.RegisterScalarFunction(
            "memos_unicode_lower", 1,
            func(_ *msqlite.FunctionContext, args []driver.Value) (driver.Value, error) {
                switch v := args[0].(type) {
                case string:
                    return unicodeFold.String(v), nil  // golang.org/x/text/cases.Fold()
                // ...
                }
            },
        )
    })
    return registerUnicodeLowerErr
}
```

渲染层用它代替 LOWER：

```go
// internal/filter/render.go — renderContainsCondition
case DialectSQLite:
    sql = fmt.Sprintf(
        "memos_unicode_lower(%s) LIKE memos_unicode_lower(%s)",
        column, r.addArg(arg),
    )
case DialectPostgres:
    sql = fmt.Sprintf("%s ILIKE %s", column, r.addArg(arg))
// MySQL: 依赖 collation 设置，直接 LIKE
```

三个方言，三种策略，统一的 IR，在渲染层分叉。

### 2.3 标签的层级匹配

标签支持 `book/fiction` 这种层级。查询 `tag in ["book"]` 应该同时匹配 `book` 和 `book/fiction`：

```go
// internal/filter/render.go — renderTagInList
case DialectSQLite:
    exactMatch := fmt.Sprintf("%s LIKE %s", jsonArrayExpr, r.addArg(`%%"%s"%%`, str))
    prefixMatch := fmt.Sprintf("%s LIKE %s", jsonArrayExpr, r.addArg(`%%"%s/%%`, str))
    expr = fmt.Sprintf("(%s OR %s)", exactMatch, prefixMatch)
```

JSON 数组存成 `["book/fiction","work"]` 字符串，精确匹配用 `%"book"%`，前缀匹配用 `%"book/%`。不依赖数据库 JSON 函数的高级特性，SQLite 兼容性好。

### 2.4 CEL 作为查询 DSL 的完整设计

Schema 是核心，把字段和 CEL 变量绑定：

```go
// internal/filter/schema.go
"tags": {
    Kind:     FieldKindJSONList,
    Column:   Column{Table: "memo", Name: "payload"},
    JSONPath: []string{"tags"},   // JSON_EXTRACT(payload, '$.tags')
},
"has_task_list": {
    Kind:     FieldKindJSONBool,
    JSONPath: []string{"property", "hasTaskList"},
},
"created_ts": {
    Kind:        FieldKindScalar,
    Type:        FieldTypeTimestamp,
    Expressions: map[DialectName]string{
        DialectMySQL: "UNIX_TIMESTAMP(%s)",  // MySQL 存 TIMESTAMP，需转换
        DialectPostgres: "%s",               // PG/SQLite 存 BIGINT，直接用
    },
},
```

加了 `now()` 函数支持相对时间查询：
```go
var nowFunction = cel.Function("now",
    cel.Overload("now", []*cel.Type{}, cel.IntType,
        cel.FunctionBinding(func(_ ...ref.Val) ref.Val {
            return types.Int(time.Now().Unix())
        }),
    ),
)
```

用户可以写：`created_ts > now() - 604800`（最近7天）。

### 2.5 缓存层

```go
// store/store.go — 三个独立 cache，按实体类型隔离
store := &Store{
    instanceSettingCache: cache.New(cacheConfig),  // 实例设置：变化慢
    userCache:            cache.New(cacheConfig),   // 用户数据：中等
    userSettingCache:     cache.New(cacheConfig),   // 用户设置：中等
}
// memo 不缓存，因为查询条件太多样，缓存命中率低
```

cache 本身用 `sync.Map` + `atomic.Int64` 实现，带 TTL（默认10min）和 MaxItems（1000）上限。容量不够时随机驱逐（map 遍历的随机性）。

---

## 三、深度维度 2：Quality/Review（工程质量）

### 3.1 迁移系统质量

**`embed.FS` 内嵌迁移文件**：二进制自包含，部署不依赖外部文件。

```go
//go:embed migration
var migrationFS embed.FS

//go:embed seed
var seedFS embed.FS
```

**版本判断逻辑**：
```go
func shouldApplyMigration(fileVersion, currentDBVersion, targetVersion string) bool {
    currentDBVersionSafe := getSchemaVersionOrDefault(currentDBVersion)
    return version.IsVersionGreaterThan(fileVersion, currentDBVersionSafe) &&
           version.IsVersionGreaterOrEqualThan(targetVersion, fileVersion)
}
```

**最小升级版本守卫**：
```go
// 旧装置（<v0.22）必须先升级到 v0.25.3，否则报清晰错误信息
return errors.Errorf(
    "Your Memos installation is too old...\n\n"+
    "Upgrade path:\n"+
    "1. First upgrade to v0.25.3: ...\n"+
    "2. Start the server and verify it works\n"+
    "3. Then upgrade to the latest version",
    schemaVersion, currentVersion,
)
```

**新装置走 LATEST.sql，不走增量迁移**：避免 27个版本的迁移链跑一遍。

### 3.2 Driver 接口设计

```go
// store/driver.go — 完整接口，所有方法显式声明
type Driver interface {
    GetDB() *sql.DB
    Close() error
    IsInitialized(ctx context.Context) (bool, error)
    // CRUD for: Attachment, Memo, MemoRelation, InstanceSetting,
    //           User, UserSetting, IdentityProvider, Inbox,
    //           Reaction, MemoShare
}
```

Store 是业务层（含缓存、级联逻辑），Driver 是纯 DB 操作层。分层清晰，Driver 可以换成 Postgres 或 MySQL 而上层无感知。

业务层负责级联删除：
```go
// store/memo.go — DeleteMemo
func (s *Store) DeleteMemo(ctx context.Context, delete *DeleteMemo) error {
    s.driver.DeleteMemoRelation(ctx, &DeleteMemoRelation{MemoID: &delete.ID})
    s.driver.DeleteMemoRelation(ctx, &DeleteMemoRelation{RelatedMemoID: &delete.ID})
    // 清理 attachments
    for _, a := range attachments {
        s.DeleteAttachment(ctx, &DeleteAttachment{ID: a.ID})
    }
    return s.driver.DeleteMemo(ctx, delete)
}
```

### 3.3 ConnectRPC + gRPC-Gateway 双协议

```go
// server/router/api/v1/connect_services.go
// ConnectServiceHandler 把每个 Connect 方法转发给底层 gRPC service 实现
func (s *ConnectServiceHandler) GetInstanceProfile(...) (...) {
    resp, err := s.APIV1Service.GetInstanceProfile(ctx, req.Msg)
    return connect.NewResponse(resp), convertGRPCError(err)
}
```

业务逻辑只写一遍（APIV1Service），协议转换层薄薄一层。Auth 相关方法走特殊的 `connectWithHeaderCarrier` 以处理 cookie 设置。

MetadataInterceptor 在所有响应上强制：
```go
resp.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
```
见 issue #5470，防止浏览器缓存 API 响应导致数据陈旧。

### 3.4 SSE 实时推送

```go
// server/router/api/v1/sse_handler.go
for {
    select {
    case <-ctx.Done():
        return nil  // 客户端断开
    case data, ok := <-client.events:
        fmt.Fprintf(w, "data: %s\n\n", data)
        w.(http.Flusher).Flush()
    case <-heartbeat.C:  // 30s 心跳
        fmt.Fprint(w, ": heartbeat\n\n")
        w.(http.Flusher).Flush()
    }
}
```

`X-Accel-Buffering: no` 禁用 nginx 缓冲，保证事件实时到达。

CreateMemo 内部调用（如 CreateMemoComment）会通过 context key 抑制 SSE 广播，避免重复事件：
```go
func withSuppressSSE(ctx context.Context) context.Context {
    return context.WithValue(ctx, suppressSSEKey{}, true)
}
// CreateMemoComment 调用：
memoComment, _ = s.CreateMemo(withSuppressSSE(ctx), ...)
// 后续再发 SSEEventMemoCommentCreated
```

---

## 四、简要扫描（其余四维）

### Security（安全）

**Webhook SSRF 双重防护**：
```go
// internal/webhook/validate.go — 注册时校验 URL
// 检查 DNS 解析结果是否落在保留 CIDR 内

// internal/webhook/webhook.go — 实际发送时二次校验
var safeClient = &http.Client{
    Transport: &http.Transport{
        DialContext: safeDialContext,  // 拨号时再检查一遍
    },
}
```

两层防护防 DNS rebinding：注册时解析的 IP 可能合法，但在实际发送前 IP 可能换成内网地址。`safeDialContext` 在真正建连前再做一次 IP 检查。

`AllowPrivateIPs` 全局开关允许自建环境关闭此保护（内网 webhook 场景）。

公开方法白名单：
```go
// server/router/api/v1/acl_config.go
var PublicMethods = map[string]struct{}{
    "/memos.api.v1.MemoService/ListMemos": {},
    // ... 显式白名单，默认拒绝
}
```

### Execution（执行模式）

调度器：
```go
// internal/scheduler/scheduler.go
type Scheduler struct {
    jobs   map[string]*registeredJob
    jobsMu sync.RWMutex  // 读写锁，支持并发读取 job 列表
}
```

`sync.Once` 保证全局单例（DefaultEngine、DefaultAttachmentEngine）：
```go
var defaultOnce sync.Once
func DefaultEngine() (*Engine, error) {
    defaultOnce.Do(func() {
        defaultInst, defaultErr = NewEngine(NewSchema())
    })
    return defaultInst, defaultErr
}
```

### Context（上下文管理）

Demo 模式作为简单布尔 flag 从启动配置穿透到 API 响应：
```go
// Profile.Demo → GetInstanceProfile → proto InstanceProfile.demo = true
// 前端读取后展示 banner
```
Feature flag 的最简形态：启动时决定，整个进程生命周期不变。种子数据也只在 demo 模式下 seed（`store/migrator.go: seed()`）。

### Failure（失败处理）

删除 memo 时不用数据库外键级联，而是 Go 代码手动级联，换取对"先查询后决定"逻辑的完全控制权（如删 attachment 前先 list 出来）。

迁移里的不可逆操作（`DROP TABLE`, `ALTER TABLE RENAME`）通过"先 RENAME 备份，插入数据，删旧表"模式执行：
```sql
-- store/migration/sqlite/0.26/...sql
ALTER TABLE user RENAME TO user_old;
CREATE TABLE user (...);           -- 重建
INSERT INTO user SELECT ... FROM user_old;
DROP TABLE user_old;
```

Webhook 发送失败只 warn 不 error，不影响 memo 创建的主流程：
```go
if err := s.DispatchMemoCreatedWebhook(ctx, memoMessage); err != nil {
    slog.Warn("Failed to dispatch memo created webhook", ...)
    // 不 return err
}
```

---

## 五、P0/P1/P2 模式提炼

### P0：CEL → SQL 编译器（可直接移植）

**问题**：给 Orchestrator 的记忆检索写过滤器，手写 SQL 拼接容易注入，字符串 DSL 难以扩展。

**方案**：抄 memos 的 `internal/filter` 完整架构。

```
CEL 字符串 → cel.Compile → AST → buildCondition（IR）→ renderer.Render → SQL + Args
```

**对比矩阵**：

| 方案 | 安全性 | 可扩展性 | 多方言 | 实现成本 |
|------|--------|---------|--------|---------|
| 手写 SQL 拼接 | 差（注入风险） | 差 | 需复制代码 | 低 |
| LIKE 字符串搜索 | 中 | 差 | 需适配 | 低 |
| **CEL → SQL（memos 方案）** | **好（参数化）** | **好（加字段改 schema）** | **好（render 分叉）** | 中 |
| 全文索引（FTS5）| 好 | 差（只搜内容）| 差 | 高 |

**三重验证**：
1. `store/db/sqlite/memo.go`: `filter.AppendConditions` 产出的 SQL 用 `?` 占位符，无注入。
2. `internal/filter/render.go`: `r.addArg(value)` 统一管理参数，Postgres 用 `$N` 偏移。
3. `internal/filter/engine_test.go`（存在）：有测试覆盖。

**节省时间**：避免手写3个方言的 SQL 拼接逻辑 + 注入修复 bug，保守估计 **>4h**。

**移植路径**：
```
1. 复制 internal/filter/ 整个包到 Orchestrator
2. 定义自己的 Schema（NewSchema() 里改字段映射）
3. 调用 AppendConditions(ctx, engine, filters, dialect, &where, &args)
4. 接入 store/db/ 的 ListXxx 函数
```

---

### P0：SQLite Unicode 全文搜索（CJK 必备）

**问题**：SQLite LOWER() 不支持 CJK，中文 LIKE 搜索大小写不一致。

**方案**：
```go
// 一次注册，sync.Once 保证线程安全
msqlite.RegisterScalarFunction("memos_unicode_lower", 1, func(...) {
    return unicodeFold.String(v), nil  // golang.org/x/text/cases.Fold()
})

// 使用
"memos_unicode_lower(%s) LIKE memos_unicode_lower(%s)"
```

**节省时间**：避免"CJK 搜索字符 bug"类问题，**>2h** 排查时间。

依赖：`golang.org/x/text/cases`（标准库延伸包）+ `modernc.org/sqlite`（CGO-free SQLite）。

---

### P1：payload JSON blob 模式（schema 演进弹性）

**思路**：结构化字段放正式列（id, creator_id, visibility, pinned），半结构化/频繁变化的属性放 payload TEXT（protojson）。

```
payload = '{"tags":["work","book/fiction"],"property":{"hasLink":true},"location":{}}'
```

好处：
- 加新属性不迁移表
- 可用 JSON_EXTRACT 在 SQL 里过滤
- protobuf 提供类型安全的序列化/反序列化

坏处：
- payload 里的字段无法建索引（除非生成列）
- 查询性能比独立列差（JSON_EXTRACT 全表扫描）

**适用场景**：属性变化频率高 > 查询频率高时用 blob，反之拆列。

---

### P1：双轨 ID（uid + id）

```
id  = INTEGER AUTOINCREMENT（内部 JOIN 用）
uid = TEXT UNIQUE（用户可见 URL、API resource name）
```

迁移时可重建 id 序列而不破坏外部 URL。

---

### P2：Context Key 控制副作用传播

```go
type suppressSSEKey struct{}
func withSuppressSSE(ctx context.Context) context.Context { ... }

// 内部调用不触发 SSE 广播
s.CreateMemo(withSuppressSSE(ctx), ...)
```

相比函数参数 bool flag，context key 方式在调用链深处也能控制副作用，不污染函数签名。Orchestrator 在 agent 调用 agent 时传递控制信号可以参考此模式。

---

## 六、路径依赖分析

### 为什么 Memos 能做到"存储与搜索架构干净"

1. **单一 payload blob 决策很早**：0.x 版本就确立，整个代码库都适配，没有历史债务。
2. **Driver 接口清晰**：SQLite/MySQL/Postgres 都实现同一 interface，CEL filter 渲染器在 render 层分叉。
3. **CEL 选型合理**：Google CEL 是专为表达式求值设计的，有完善的 Go 实现，比自研 DSL 省 2~3 倍工作量。
4. **modernc.org/sqlite**：CGO-free，允许注册 Go 函数作为 SQL 函数（RegisterScalarFunction），官方 CGO 版无此 API。

### Orchestrator 的路径依赖风险

- 如果已有自己的记忆存储 schema，引入 CEL filter 需要改 Driver 接口，不是零成本。
- memos_unicode_lower 依赖 `modernc.org/sqlite`，如果用 CGO sqlite3 需要用 sqlite3_create_function_v2（C 层）替代。
- payload blob 的查询性能在大数据量（>10w 记忆条目）会有问题，届时需要为 tags/property 字段建生成列索引。

---

## 七、总结

memos 在"个人知识存储"这个细分领域的工程质量远超预期。最值得偷的三件事：

1. **CEL → SQL 编译器**：类型安全、多方言、可扩展，直接抄 `internal/filter/` 包。
2. **SQLite Unicode 函数注册**：解决 CJK 全文搜索问题，10 行代码节省若干 bug 排查时间。
3. **SSE 抑制 context key 模式**：嵌套调用时控制副作用的干净方案。

迁移系统和 webhook SSRF 防护是加分项，可以按需参考。
