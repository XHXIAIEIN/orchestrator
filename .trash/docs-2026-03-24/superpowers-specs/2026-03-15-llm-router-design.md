# LLM Router — 本地模型接入层设计

## 目标

让 Orchestrator 的 LLM 调用不再 100% 依赖 Anthropic API。引入统一路由层 `llm_router.py`，按任务类型把请求分发到 Claude（云端）或 Ollama（本地）。

## 核心原则

- **Claude 当总指挥**：深度分析、战略推荐、复杂推理留给 Claude
- **本地干杂活**：审查、摘要、债务扫描等结构化输出任务用 Ollama
- **零侵入切换**：每个调用点改为 `llm_router.generate(...)`，调用方保留自己的 JSON 解析逻辑
- **可回退**：Ollama 挂了或返回垃圾自动 fallback 到 Claude
- **可手动覆盖**：环境变量 `LLM_FORCE_CLAUDE=scrutiny,debt_scan` 可把指定任务强制回退到 Claude

## 路由表

| 调用点 | 当前 | 改后 | 理由 |
|--------|------|------|------|
| Governor.scrutinize() | claude --print (Haiku) | Ollama qwen3:32b | APPROVE/REJECT 二选一，本地秒出 |
| DebtScanner._analyze_one_batch() | claude --print (Haiku) | Ollama qwen3:32b | JSON 数组提取，结构化输出 |
| DailyAnalyst.run() | claude --print (Sonnet) | **第二波再切** | 涉及 profile_update 写 DB，需先验证 scrutiny/debt_scan 稳定 |
| InsightEngine.run() | claude --print (Sonnet) | **保留 Claude** | 7 天深度分析+推荐生成，需要最强推理 |
| ProfileAnalyst.run() | claude --print (Sonnet) | **保留 Claude** | 用户画像演进需要细腻理解 |
| Governor.execute_task() | claude CLI (sub-agent) | **保留 Claude** | 需要工具调用能力 |

## 架构

```
src/
├── llm_router.py          # 新增：统一路由层（含 Ollama 配置）
├── governor.py            # 改造：scrutinize() 走 router
├── debt_scanner.py        # 改造：_analyze_one_batch() 走 router
├── analyst.py             # 不动（第二波再切）
├── config.py              # 不动（保持纯认证职责）
└── ...
```

### llm_router.py 接口

```python
class LLMRouter:
    def generate(self,
        prompt: str,
        task_type: str,          # "scrutiny" | "summary" | "debt_scan" | "deep_analysis" | "profile"
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """统一入口。根据 task_type 查路由表决定后端。"""

    def _ollama_generate(self, prompt, model, max_tokens, temperature) -> str:
        """调 Ollama REST API (http://localhost:11434/api/generate)"""

    def _claude_generate(self, prompt, model, max_tokens, temperature) -> str:
        """调 Claude CLI (claude --print)"""
```

### 路由配置

```python
ROUTES = {
    "scrutiny":      {"backend": "ollama", "model": "qwen3:32b", "timeout": 20,  "fallback": "claude"},
    "debt_scan":     {"backend": "ollama", "model": "qwen3:32b", "timeout": 60,  "fallback": "claude"},
    "summary":       {"backend": "claude", "model": "claude-haiku-4-5-20251001", "timeout": 120},  # 第二波再切 Ollama
    "deep_analysis": {"backend": "claude", "model": "claude-sonnet-4-6",         "timeout": 120},
    "profile":       {"backend": "claude", "model": "claude-sonnet-4-6",         "timeout": 120},
}
# 环境变量覆盖：LLM_FORCE_CLAUDE=scrutiny,debt_scan → 强制走 Claude
```

### Ollama 集成方式

直接 HTTP 调用 Ollama REST API，不引入新依赖：
- `POST http://localhost:11434/api/generate` — 文本生成（`stream: false`）
- `GET http://localhost:11434/api/tags` — 启动时检查可用模型
- 超时按任务类型配置（scrutiny=20s, debt_scan=60s）
- 失败自动 fallback 到 Claude（连接失败、超时、空响应都触发）
- **垃圾输出检测**：响应为空或少于 10 字符时视为失败，触发 fallback

### Docker 集成

docker-compose.yml 需要让容器能访问宿主机的 Ollama：
- 方案：`extra_hosts: ["host.docker.internal:host-gateway"]`
- Ollama URL: `http://host.docker.internal:11434`
- 环境变量: `OLLAMA_HOST=http://host.docker.internal:11434`

## 改造范围

### 1. 新增 `src/llm_router.py`（~120 行）
- LLMRouter 类（单例）
- 路由表 + 环境变量覆盖逻辑 (`LLM_FORCE_CLAUDE`)
- Ollama HTTP 客户端（urllib，不加依赖）
- Claude CLI 封装（统一用 stdin 传 prompt，解决参数长度限制）
- Fallback 逻辑：连接失败 / 超时 / 空响应 / 垃圾输出 → 自动切 Claude
- 每次调用记录日志：`router: [ollama] scrutiny 1.2s ok` 或 `router: [fallback] scrutiny ollama_timeout -> claude 3.4s`
- 启动时探测 Ollama 可达性，日志报告本地路由是否激活

### 2. 改造 `src/governor.py`（~10 行改动）
- `scrutinize()`: subprocess.run → `router.generate(prompt, task_type="scrutiny")`
- 保留 VERDICT 解析逻辑不变

### 3. 改造 `src/debt_scanner.py`（~10 行改动）
- `_analyze_one_batch()`: subprocess.run → `router.generate(prompt, task_type="debt_scan")`
- 保留 JSON 解析和 markdown fence 剥离逻辑不变

### 4. 改造 `docker-compose.yml`（+3 行）
- 加 `extra_hosts` 和 `OLLAMA_HOST` 环境变量

### 5. 不动的文件
- `src/config.py` — 保持纯认证职责，Ollama 配置放在 `llm_router.py` 内
- `src/analyst.py` — 第二波再切，本轮不动
- `src/insights.py` — 保留 Claude
- `src/profile_analyst.py` — 保留 Claude
- `src/scheduler.py` — 不受影响
- `requirements.txt` — 无新依赖

## 不做的事

- 不改 InsightEngine、ProfileAnalyst、Governor.execute_task() — 这些留给 Claude
- 不改 DailyAnalyst — 第二波验证后再切（涉及 profile_update 写 DB）
- 不引入 Ollama Python SDK — 一个 HTTP POST 不需要库
- 不做模型自动下载 — 假设 Ollama 已有 qwen3:32b
- 不做流式输出 — 内部组件不需要
- 不改 Dashboard — 这一轮不涉及前端
- 不做 HTTP 连接池 — 调用频率低（每小时几次），未来按需加

## GPU 资源注意

qwen3:32b Q4 量化约占 20GB VRAM。RTX 5090 24GB 能跑，但如果同时跑 ComfyUI 生图会 OOM。
Orchestrator 的调用频率低（每小时几次），不会长期占用显存——Ollama 默认在空闲 5 分钟后卸载模型。

## 验证方式

1. 确保 Ollama 在宿主机运行且 qwen3:32b 可用
2. 重启容器后 Governor 审查走本地（日志可见 `[ollama]` 标记）
3. DailyAnalyst 生成的摘要 JSON 格式正确
4. DebtScanner 批次分析输出 debt 数组
5. Ollama 挂掉时自动 fallback 到 Claude（日志可见 `[fallback]`）
6. InsightEngine 和 ProfileAnalyst 仍走 Claude（不受影响）
