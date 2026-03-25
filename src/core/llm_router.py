"""
LLM Router — 统一路由层。
按 task_type 决定走 Ollama（本地）还是 Claude API SDK（云端）。
Ollama 失败自动 fallback 到 Claude。
"""
import base64
import json
import logging
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

MODEL_TIERS = {
    # Chrome AI — 端侧免费，仅桌面环境可用
    "chrome-ai/summarizer":        {"cost": 0, "capability": 0.4,  "multimodal": False, "env": "desktop"},
    "chrome-ai/translator":        {"cost": 0, "capability": 0.5,  "multimodal": False, "env": "desktop"},
    "chrome-ai/language-detector": {"cost": 0, "capability": 0.8,  "multimodal": False, "env": "desktop"},
    "chrome-ai/prompt":            {"cost": 0, "capability": 0.35, "multimodal": False, "env": "desktop"},
    "ollama/qwen2.5:7b":         {"cost": 0,    "capability": 0.5,  "multimodal": False},
    "ollama/qwen3.5:9b":         {"cost": 0,    "capability": 0.55, "multimodal": False},
    "ollama/deepseek-r1:14b":    {"cost": 0,    "capability": 0.6,  "multimodal": False},
    "claude-haiku-4-5-20251001": {"cost": 0.25, "capability": 0.7,  "multimodal": False},
    "ollama/gemma3:27b":         {"cost": 0,    "capability": 0.65, "multimodal": True},
    "claude-sonnet-4-6":         {"cost": 3.0,  "capability": 0.9,  "multimodal": True},
}

ROUTES = {
    "scrutiny":      {"cascade": ["ollama/deepseek-r1:14b", "claude-haiku-4-5-20251001"], "timeout": 45, "no_think": True},
    "debt_scan":     {"cascade": ["ollama/deepseek-r1:14b", "claude-haiku-4-5-20251001"], "timeout": 90, "no_think": True},
    "summary":       {"backend": "claude", "model": "claude-haiku-4-5-20251001",  "timeout": 120},
    "deep_analysis": {"cascade": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"], "timeout": 120},
    "profile":       {"backend": "claude", "model": "claude-sonnet-4-6",          "timeout": 120},
    # 多模态路由 — 不适合 cascade
    "vision":        {"backend": "ollama", "model": "gemma3:27b",                 "timeout": 90},
    "ocr":           {"backend": "ollama", "model": "gemma3:27b",                 "timeout": 90},
    # GUI 自动化推理 — 多模态，优先 Ollama，fallback 到 Claude
    "gui_reason":    {"backend": "ollama", "model": "gemma3:27b",                 "timeout": 60,  "fallback": "claude", "fallback_model": "claude-haiku-4-5-20251001"},
    # Channel 闲聊 — 非推理模型更快更稳（qwen3.5 的 thinking 对闲聊是浪费）
    "chat":          {"cascade": ["ollama/qwen2.5:7b", "claude-haiku-4-5-20251001"], "timeout": 15, "no_think": True},
    # Channel 需要推理的对话 — deepseek-r1
    "chat_reason":   {"cascade": ["ollama/deepseek-r1:14b", "ollama/qwen3.5:9b"], "timeout": 90},
    # Chrome AI 路由 — 端侧免费，桌面环境优先
    "translate":     {"cascade": ["chrome-ai/translator", "claude-haiku-4-5-20251001"], "timeout": 15},
    "lang_detect":   {"backend": "chrome-ai", "model": "language-detector", "timeout": 5,
                      "fallback": "claude", "fallback_model": "claude-haiku-4-5-20251001"},
}

MIN_RESPONSE_LEN = 10  # 少于这个字符数视为垃圾输出


class LLMRouter:
    def __init__(self):
        self._ollama_available = None  # lazy probe

    def generate(self, prompt: str, task_type: str,
                 max_tokens: int = 1024, temperature: float = 0.3,
                 images: list[str] | None = None) -> str:
        """统一入口。根据 task_type 查路由表决定后端。
        images: 可选的图片列表（文件路径或 base64 字符串）。仅 Ollama 多模态路由支持。
        """
        route = ROUTES.get(task_type)
        if not route:
            raise ValueError(f"Unknown task_type: {task_type}")

        # 环境变量强制覆盖（cascade 路由也受此影响：跳过 cascade 直接走 Claude）
        force_claude = os.environ.get("LLM_FORCE_CLAUDE", "")
        if force_claude and task_type in [t.strip() for t in force_claude.split(",")]:
            log.info(f"router: [force_claude] {task_type} overridden to claude")
            model = route.get("model", route.get("cascade", ["claude-haiku-4-5-20251001"])[-1])
            if model.startswith("ollama/"):
                model = "claude-haiku-4-5-20251001"
            return self._claude_generate(prompt, model, route["timeout"], max_tokens,
                                         self._encode_images(images) if images else None)

        # 编码图片为 base64
        b64_images = self._encode_images(images) if images else None

        # 有 cascade 字段 → 走级联
        if "cascade" in route:
            return self._generate_cascade(prompt, route, max_tokens, temperature, b64_images)

        # 无 cascade → 走原有逻辑
        backend = route["backend"]

        if backend == "chrome-ai":
            model_id = f"chrome-ai/{route['model']}"
            result = self._chrome_ai_generate(prompt, model_id, max_tokens)
            if result and len(result) >= MIN_RESPONSE_LEN:
                return result
            # fallback 到 Claude
            if route.get("fallback") == "claude":
                fallback_model = route.get("fallback_model", "claude-haiku-4-5-20251001")
                log.info(f"router: chrome-ai {task_type} fallback -> {fallback_model}")
                return self._claude_generate(prompt, fallback_model, route["timeout"], max_tokens)
            return result or ""
        elif backend == "ollama":
            # Qwen3 系列默认开 thinking，对简单任务追加 /no_think 关闭
            if route.get("no_think") and not prompt.rstrip().endswith("/no_think"):
                prompt = prompt.rstrip() + "\n\n/no_think"
            return self._ollama_with_fallback(
                prompt, task_type, route, max_tokens, temperature, b64_images
            )
        else:
            return self._claude_generate(
                prompt, route["model"], route["timeout"], max_tokens
            )

    @staticmethod
    def _encode_images(images: list[str]) -> list[str]:
        """将图片路径或 base64 字符串统一转为 base64 列表。"""
        result = []
        for img in images:
            p = Path(img)
            if p.exists() and p.is_file():
                result.append(base64.b64encode(p.read_bytes()).decode())
            elif len(img) > 260:  # 已经是 base64
                result.append(img)
            else:
                log.warning(f"router: image not found: {img}")
        return result

    def _generate_cascade(self, prompt: str, route: dict,
                           max_tokens: int, temperature: float,
                           images: list[str] | None = None) -> str:
        """级联尝试：从便宜到贵。"""
        cascade = route["cascade"]
        attempts = []

        for model_id in cascade:
            # Chrome AI 分支 — 端侧模型，headless 环境自动跳过
            if model_id.startswith("chrome-ai/"):
                tier = MODEL_TIERS.get(model_id, {})
                if tier.get("env") == "desktop" and os.environ.get("BROWSER_HEADLESS", "false").lower() == "true":
                    attempts.append({"model": model_id, "reason": "headless_environment"})
                    continue
                try:
                    result = self._chrome_ai_generate(prompt, model_id, max_tokens)
                    if result and len(result) >= MIN_RESPONSE_LEN:
                        log.info(f"router: cascade success with {model_id}")
                        return result
                    attempts.append({"model": model_id, "reason": f"short_response ({len(result or '')} chars)"})
                except Exception as e:
                    attempts.append({"model": model_id, "reason": str(e)})
                continue

            # 解析 model_id 格式: "ollama/xxx" 或 "claude-xxx"
            if model_id.startswith("ollama/"):
                model_name = model_id.split("/", 1)[1]
                backend = "ollama"
            else:
                model_name = model_id
                backend = "claude"

            # 跳过不可达的 ollama
            if backend == "ollama" and self._ollama_available is False:
                attempts.append({"model": model_id, "reason": "ollama_unavailable"})
                continue

            try:
                if backend == "ollama":
                    # Qwen3 no_think
                    p = prompt
                    if route.get("no_think") and not p.rstrip().endswith("/no_think"):
                        p = p.rstrip() + "\n\n/no_think"
                    result = self._ollama_generate(p, model_name, route["timeout"],
                                                   max_tokens, temperature, images)
                else:
                    result = self._claude_generate(prompt, model_name, route["timeout"],
                                                   max_tokens, images)

                if len(result.strip()) >= MIN_RESPONSE_LEN:
                    tier = MODEL_TIERS.get(model_id, {})
                    log.info(f"router: [cascade] {model_id} ok ({len(result)} chars, "
                             f"cost_tier={tier.get('cost', '?')}, attempts={len(attempts)+1})")
                    return result

                attempts.append({"model": model_id, "reason": f"low_quality ({len(result.strip())} chars)"})
            except Exception as e:
                attempts.append({"model": model_id, "reason": str(e)})

        # 全部失败
        log.warning(f"router: [cascade] all models failed: {attempts}")
        return ""

    def _ollama_with_fallback(self, prompt: str, task_type: str, route: dict,
                               max_tokens: int, temperature: float,
                               images: list[str] | None = None) -> str:
        """尝试 Ollama，失败则 fallback 到 Claude。"""
        # 启动探测发现 Ollama 不可达 → 直接走 Claude（多模态路由无 fallback）
        if self._ollama_available is False:
            if route.get("fallback"):
                log.info(f"router: [skip_ollama] {task_type} -> claude (ollama unavailable)")
                return self._claude_fallback(prompt, task_type, route, max_tokens, images)
            log.warning(f"router: [skip_ollama] {task_type} failed (ollama unavailable, no fallback)")
            return ""

        t0 = time.time()
        try:
            result = self._ollama_generate(
                prompt, route["model"], route["timeout"], max_tokens, temperature, images
            )
            elapsed = time.time() - t0

            if len(result.strip()) < MIN_RESPONSE_LEN:
                if route.get("fallback"):
                    log.warning(f"router: [fallback] {task_type} ollama_garbage ({len(result.strip())} chars) -> claude")
                    return self._claude_fallback(prompt, task_type, route, max_tokens, images)
                log.warning(f"router: [error] {task_type} ollama_garbage ({len(result.strip())} chars), no fallback")
                return result

            log.info(f"router: [ollama] {task_type} {elapsed:.1f}s ok ({len(result)} chars)")
            return result

        except Exception as e:
            elapsed = time.time() - t0
            reason = type(e).__name__
            if route.get("fallback"):
                log.warning(f"router: [fallback] {task_type} ollama_{reason} ({elapsed:.1f}s) -> claude")
                return self._claude_fallback(prompt, task_type, route, max_tokens, images)
            log.warning(f"router: [error] {task_type} ollama_{reason} ({elapsed:.1f}s), no fallback")
            return ""

    def _claude_fallback(self, prompt: str, task_type: str, route: dict,
                          max_tokens: int,
                          images: list[str] | None = None) -> str:
        """Fallback 到 Claude API（支持多模态）。"""
        fallback_model = route.get("fallback_model", "claude-haiku-4-5-20251001")
        t0 = time.time()
        result = self._claude_generate(prompt, fallback_model, route["timeout"],
                                        max_tokens, images)
        elapsed = time.time() - t0
        log.info(f"router: [claude_fallback] {task_type} {elapsed:.1f}s ok")
        return result

    def _ollama_generate(self, prompt: str, model: str, timeout: int,
                          max_tokens: int, temperature: float,
                          images: list[str] | None = None) -> str:
        """调 Ollama REST API。支持多模态（images 为 base64 列表）。"""
        url = f"{OLLAMA_HOST}/api/generate"
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if images:
            body["images"] = images
        payload = json.dumps(body).encode()

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data.get("response", "")

    def _claude_generate(self, prompt: str, model: str, timeout: int,
                          max_tokens: int,
                          images: list[str] | None = None) -> str:
        """调 Claude API SDK。支持多模态（images 为 base64 列表）。"""
        from src.core.config import get_anthropic_client
        try:
            client = get_anthropic_client()

            # 构建消息内容：有图片时用多模态格式
            if images:
                content = []
                for img_b64 in images:
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64,
                        },
                    })
                content.append({"type": "text", "text": prompt})
            else:
                content = prompt

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": content}],
            )
            text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            return text.strip()
        except Exception as e:
            log.error(f"router: Claude API failed: {e}")
            return ""

    def _chrome_ai_generate(self, prompt: str, model_id: str, max_tokens: int) -> Optional[str]:
        """调用 Chrome AI API。需要 BrowserAI 实例可用。"""
        try:
            from src.core.browser_ai import BrowserAI
            from src.core.browser_runtime import BrowserRuntime
        except ImportError:
            return None

        # 懒初始化 BrowserAI
        if not hasattr(self, '_browser_ai'):
            rt = BrowserRuntime.from_env()
            if not rt.available:
                self._browser_ai = None
                return None
            self._browser_ai = BrowserAI(rt)

        if self._browser_ai is None:
            return None

        ai_type = model_id.split("/", 1)[1]  # "summarizer", "translator", etc.

        if ai_type == "summarizer":
            return self._browser_ai.summarize_sync(prompt)
        elif ai_type == "translator":
            # 简单处理：prompt 包含翻译指令，直接当摘要用
            return self._browser_ai.summarize_sync(prompt)
        elif ai_type == "language-detector":
            result = self._browser_ai.detect_language_sync(prompt)
            if result:
                return json.dumps(result)
            return None
        elif ai_type == "prompt":
            return self._browser_ai.summarize_sync(prompt)
        else:
            return None

    def check_ollama(self) -> bool:
        """探测 Ollama 是否可达 + 检查所需模型。启动时调用一次。"""
        try:
            url = f"{OLLAMA_HOST}/api/tags"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            models = [m.get("name", "") for m in data.get("models", [])]
            log.info(f"router: Ollama reachable, models: {models}")
            # 检查路由表中需要的模型是否存在
            needed = {r["model"] for r in ROUTES.values() if r.get("backend") == "ollama"}
            for m in needed:
                if not any(m in avail for avail in models):
                    log.warning(f"router: Ollama model '{m}' not found, run: ollama pull {m}")
            self._ollama_available = True
            return True
        except Exception as e:
            log.warning(f"router: Ollama unreachable ({e}), all tasks will use Claude")
            self._ollama_available = False
            return False


# 模块级单例
_router = None

def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
        _router.check_ollama()
    return _router
