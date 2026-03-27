# Lumina OS (fractalsense-ai)

- **URL**: https://github.com/fractalsense-ai/lumina-os
- **评级**: S 级（含金量最高）

## 一句话

零信任、确定性的 AI 编排层——LLM 只是"处理单元"，不是"权威"。

## 核心架构：D.S.A. 三支柱

| 支柱 | 角色 | 可变性 |
|------|------|--------|
| Domain（域物理） | 不可变规则集——不变量、standing orders、升级触发器 | 会话内不可变 |
| State（状态） | 实体的压缩表示，从结构化证据增量更新 | 可变 |
| Action（行动） | 编排器在 Domain 约束内决定的响应 | 受 Domain 约束 |

## 可偷模式

### 1. Domain Pack 模式 ⭐⭐⭐⭐⭐
核心引擎零领域代码，所有领域行为通过声明式配置 + 动态加载的 callable 注入。切换领域只改一个环境变量。

→ 每个部门自带 prompt/工具/状态机，核心编排层完全无感。

### 2. 哈希链审计日志 ⭐⭐⭐⭐⭐
每条记录携带 prev_record_hash (SHA-256)。SQLite 触发器阻止 UPDATE/DELETE。

→ run-log.jsonl 加一层 prev_hash 链，从"日志"升级为"账本"。

### 3. SLM 预消化上下文 ⭐⭐⭐⭐
用小模型预处理领域知识，压缩后注入 LLM context。降低 token 消耗。

### 4. 确定性模板 fallback ⭐⭐⭐⭐
`deterministic_templates` 映射 action → 模板字符串，LLM 不可用时系统仍能运转。

### 5. 检查中间件管道 ⭐⭐⭐⭐
LLM 产出和执行之间的确定性屏障：NLP 预处理 → Schema 验证 → 不变量检查。Critical 违反直接拒绝。

### 6. 策略承诺门 ⭐⭐⭐
会话启动时活跃域物理的 SHA-256 哈希必须匹配 CommitmentRecord。配置篡改在执行前检测。

### 7. 新颖合成追踪 ⭐⭐⭐
LLM 产出无法被现有规则分类时进入双钥匙验证门（领域信号 + 人类审核）。

## 不建议偷
- 零信任安全层（JWT/RBAC/Argon2id）对本地编排器过度工程
- 分形治理层级对单用户项目意义不大
