# guideline: db-changes
## 触发条件
关键词: database, schema, migration, events.db, sqlite, ALTER, 表结构, 字段, db
## 规则
- 改 schema 前备份当前 DB
- 写 migration 而不是直接 ALTER TABLE
- 确保向后兼容
- 改完后验证 DB 能正常打开和查询
## 爆炸半径
HIGH
