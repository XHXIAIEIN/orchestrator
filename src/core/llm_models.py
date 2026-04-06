"""
LLM Models — 模型常量、路由表、质量阈值、深度档位、响应结构。
从 llm_router.py 拆分出来，所有模块应从此处导入模型常量。
"""
import os
from dataclasses import dataclass, field

# ── 模型常量 — 全系统唯一的模型名定义点 ──
# 其他模块应从此处导入，不要硬编码模型名。
# 更换模型只改这里。
MODEL_OPUS = "claude-opus-4-6"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5-20251001"
# Ollama 本地模型
MODEL_QWEN_CHAT = "qwen3.5:9b"         # 闲聊 + 轻量推理（统一用 3.5）
MODEL_QWEN_THINK = "qwen3.5:9b"        # 带推理（同模型，路由保留语义区分）
MODEL_DEEPSEEK = "deepseek-r1:14b"      # 深度推理
MODEL_GEMMA_VISION = "gemma4:26b"       # 多模态（视觉）+ 深度推理（MoE）

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Ollama 路由用的 prefixed ID（"ollama/" + 模型名）
_OL_QWEN_CHAT = f"ollama/{MODEL_QWEN_CHAT}"
_OL_QWEN_THINK = f"ollama/{MODEL_QWEN_THINK}"
_OL_DEEPSEEK = f"ollama/{MODEL_DEEPSEEK}"
_OL_GEMMA = f"ollama/{MODEL_GEMMA_VISION}"

MODEL_TIERS = {
    # Chrome AI — 端侧免费，仅桌面环境可用
    "chrome-ai/summarizer":        {"cost": 0, "capability": 0.4,  "multimodal": False, "env": "desktop",
                                    "speed": 9, "vision": False, "json_mode": False, "max_output": 1024},
    "chrome-ai/translator":        {"cost": 0, "capability": 0.5,  "multimodal": False, "env": "desktop",
                                    "speed": 9, "vision": False, "json_mode": False, "max_output": 1024},
    "chrome-ai/language-detector": {"cost": 0, "capability": 0.8,  "multimodal": False, "env": "desktop",
                                    "speed": 10, "vision": False, "json_mode": False, "max_output": 256},
    "chrome-ai/prompt":            {"cost": 0, "capability": 0.35, "multimodal": False, "env": "desktop",
                                    "speed": 9, "vision": False, "json_mode": False, "max_output": 2048},
    _OL_QWEN_CHAT:               {"cost": 0,    "capability": 0.6,  "multimodal": False,
                                   "speed": 8, "vision": False, "json_mode": True,  "max_output": 4096},
    _OL_DEEPSEEK:                {"cost": 0,    "capability": 0.6,  "multimodal": False,
                                   "speed": 4, "vision": False, "json_mode": True,  "max_output": 8192},
    MODEL_HAIKU:                 {"cost": 0.25, "capability": 0.7,  "multimodal": True,
                                  "speed": 8, "vision": True,  "json_mode": True,  "max_output": 8192},
    _OL_GEMMA:                   {"cost": 0,    "capability": 0.72, "multimodal": True,
                                  "speed": 3, "vision": True,  "json_mode": True,  "max_output": 8192},
    MODEL_SONNET:                {"cost": 3.0,  "capability": 0.9,  "multimodal": True,
                                  "speed": 7, "vision": True,  "json_mode": True,  "max_output": 16384},
}


# ── Feature Flag Engine Selection（偷自 Firecrawl feature-flag 矩阵）──
# 按需求特征筛选引擎，而不是硬编码路由。
# required 示例: {"vision": True, "json_mode": True, "min_output": 8000}

def select_engine_by_features(
    required: dict,
    preference: str = "cost",
    exclude: set[str] | None = None,
) -> list[str]:
    """根据 feature 需求筛选引擎，按偏好排序返回。

    Args:
        required: 硬性需求字典。支持的 key：
            - vision (bool): 需要图像理解
            - json_mode (bool): 需要结构化 JSON 输出
            - min_output (int): 最小输出 token 数
            - min_capability (float): 最低能力分（0-1）
            - local_only (bool): 仅本地模型（cost=0）
        preference: 排序策略 — "cost"（最便宜优先）、"speed"（最快优先）、
                    "quality"（最强优先）
        exclude: 排除的引擎 ID 集合

    Returns:
        符合条件的引擎 ID 列表，按偏好排序。空列表 = 没有引擎满足需求。
    """
    exclude = exclude or set()
    candidates = []

    for engine_id, feat in MODEL_TIERS.items():
        if engine_id in exclude:
            continue
        # ── 硬性过滤 ──
        if required.get("vision") and not feat.get("vision"):
            continue
        if required.get("json_mode") and not feat.get("json_mode"):
            continue
        if required.get("min_output", 0) > feat.get("max_output", 0):
            continue
        if required.get("min_capability", 0) > feat.get("capability", 0):
            continue
        if required.get("local_only") and feat.get("cost", 0) > 0:
            continue
        # desktop-only 引擎在非桌面环境不可用
        if feat.get("env") == "desktop":
            import os as _os
            if _os.environ.get("BROWSER_HEADLESS", "false").lower() == "true":
                continue
        candidates.append((engine_id, feat))

    # ── 按偏好排序 ──
    _sort_keys = {
        "cost":    lambda x: (x[1]["cost"], -x[1].get("speed", 0)),
        "speed":   lambda x: (-x[1].get("speed", 0), x[1]["cost"]),
        "quality": lambda x: (-x[1].get("capability", 0), x[1]["cost"]),
    }
    candidates.sort(key=_sort_keys.get(preference, _sort_keys["cost"]))
    return [eid for eid, _ in candidates]

ROUTES = {
    "scrutiny":      {"cascade": [_OL_DEEPSEEK, MODEL_HAIKU], "timeout": 45, "no_think": True},
    "debt_scan":     {"cascade": [_OL_DEEPSEEK, MODEL_HAIKU], "timeout": 90, "no_think": True},
    "summary":       {"backend": "claude", "model": MODEL_HAIKU,  "timeout": 120},
    "deep_analysis": {"cascade": [_OL_GEMMA, MODEL_HAIKU, MODEL_SONNET], "timeout": 120},
    "profile":       {"backend": "claude", "model": MODEL_SONNET, "timeout": 120},
    # 多模态路由 — 不适合 cascade
    "vision":        {"backend": "ollama", "model": MODEL_GEMMA_VISION, "timeout": 90, "fallback": "claude", "fallback_model": MODEL_HAIKU},
    "ocr":           {"backend": "ollama", "model": MODEL_GEMMA_VISION, "timeout": 90, "fallback": "claude", "fallback_model": MODEL_HAIKU},
    # GUI 自动化推理 — 多模态，优先 Ollama，fallback 到 Claude
    "gui_reason":    {"backend": "ollama", "model": MODEL_GEMMA_VISION, "timeout": 60, "fallback": "claude", "fallback_model": MODEL_HAIKU},
    # Channel 闲聊 — 非推理模型更快更稳
    "chat":          {"cascade": [_OL_QWEN_CHAT, MODEL_HAIKU], "timeout": 15, "no_think": True},
    # Channel 需要推理的对话
    "chat_reason":   {"cascade": [_OL_QWEN_CHAT, _OL_GEMMA], "timeout": 90},
    # Chrome AI 路由 — 端侧免费，桌面环境优先
    "translate":     {"cascade": ["chrome-ai/translator", MODEL_HAIKU], "timeout": 15},
    "lang_detect":   {"backend": "chrome-ai", "model": "language-detector", "timeout": 5,
                      "fallback": "claude", "fallback_model": MODEL_HAIKU},
}

MIN_RESPONSE_LEN = 10  # 少于这个字符数视为垃圾输出（basic 档默认值）

# ── 质量阈值语义枚举 — 偷自 Brave context_threshold_mode ──
# 用语义名称代替裸数字，让调用方不需要猜 "10 是什么意思"。
THRESHOLD_MODES = {
    "strict":   {"min_response_len": 50,  "desc": "严格 — 短于 50 字符视为垃圾"},
    "balanced": {"min_response_len": 10,  "desc": "平衡 — 默认行为"},
    "lenient":  {"min_response_len": 3,   "desc": "宽松 — 几乎接受所有非空响应"},
    "disabled": {"min_response_len": 0,   "desc": "禁用 — 不做质量过滤"},
}
DEFAULT_THRESHOLD = "balanced"


def get_min_response_len(threshold: str = DEFAULT_THRESHOLD) -> int:
    """根据 threshold mode 返回最小响应长度。"""
    mode = THRESHOLD_MODES.get(threshold, THRESHOLD_MODES[DEFAULT_THRESHOLD])
    return mode["min_response_len"]

# ── 深度档位 — 偷自 Tavily 的 search_depth 设计 ──
# depth 是调用方的"算力预算声明"，与 task_type（能力需求）正交组合。
# timeout_mult: 乘以路由表 timeout    max_cascade: 截断 cascade 列表长度
# max_tokens_cap: 硬性截断 max_tokens  retry: 失败后重试次数（仅 advanced）
DEPTH_TIERS = {
    "ultra-fast": {"timeout_mult": 0.3, "max_cascade": 1, "max_tokens_cap": 256,  "retry": 0},
    "fast":       {"timeout_mult": 0.6, "max_cascade": 1, "max_tokens_cap": 512,  "retry": 0},
    "basic":      {"timeout_mult": 1.0, "max_cascade": None, "max_tokens_cap": None, "retry": 0},
    "advanced":   {"timeout_mult": 2.0, "max_cascade": None, "max_tokens_cap": None, "retry": 1},
}
DEFAULT_DEPTH = "basic"


# ── 响应结构 — 偷自 Exa costDollars + Parallel usage SKU ──
# generate() 返回纯 str（向后兼容），generate_rich() 返回 GenerateResult。
@dataclass
class GenerateResult:
    """LLM 调用的结构化结果，附带成本和诊断元数据。"""
    text: str
    model_used: str = ""               # 实际使用的模型 ID
    task_type: str = ""
    depth: str = DEFAULT_DEPTH
    latency_ms: int = 0                # 端到端延迟
    cost_dollars: float = 0.0          # 估算美元成本（基于 MODEL_TIERS.cost × tokens）
    attempts: list[dict] = field(default_factory=list)  # cascade 尝试记录
    warnings: list[str] = field(default_factory=list)   # 非致命警告

    def __str__(self) -> str:
        return self.text

    def __bool__(self) -> bool:
        return bool(self.text.strip())
