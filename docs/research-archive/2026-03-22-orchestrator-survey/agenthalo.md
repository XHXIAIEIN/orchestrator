# Agent H.A.L.O. (Abraxas1010)

- **URL**: https://github.com/Abraxas1010/agenthalo
- **语言**: Rust ~98K 行 + Lean 4 + Solidity
- **评级**: B 级（过度工程，但有亮点）

## 一句话

主权 AI Agent 平台——密码学身份 + 防篡改审计 + 后量子通信 + 形式化验证，全部本地运行。

## 可偷模式

### 1. StreamAdapter trait ⭐⭐⭐⭐
统一 Claude/Codex/Gemini 三种 CLI 输出格式解析。`parse_line` + `finalize` + `detected_model`。新增 Agent 零侵入。

### 2. PipeTransform DAG ⭐⭐⭐⭐
任务间数据流转枚举：Identity | ClaudeAnswer | JsonExtract(path) | Prefix | Suffix | Chain。可序列化，比硬编码 pipeline 灵活。

### 3. ContainerBudget ⭐⭐⭐⭐
max_agents + max_concurrent_busy + allowed_kinds 三维资源约束。

→ 三省六部派单的预算模型。

### 4. Content-Addressed Tracing ⭐⭐⭐⭐
所有 trace 事件带 SHA-512 content hash，可事后验证日志未被篡改。

→ run-log.jsonl 升级方向。

### 5. Vault 环境变量 ⭐⭐⭐
`vault:provider_name` 语法声明式引用加密 API key。

### 6. Subsidiary Registry ⭐⭐⭐
Operator/Subsidiary 架构 + 文件锁 + 原子写入。多 agent 委派的所有权管理。

## 不建议偷
- 后量子密码学（ML-KEM-768/ML-DSA-65）——过度工程
- 自研数据库 NucleusDB——SQLite 够用
- Lean 4 形式化验证——维护成本极高
- 整体 98K 行 Rust 对一个 orchestrator 来说太重了
