"""
LLM Router — 统一路由层。
按 task_type 决定走 Ollama（本地）还是 Claude CLI（云端）。
Ollama 失败自动 fallback 到 Claude。
"""
import base64
import json
import logging
import os
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

log = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

ROUTES = {
    "scrutiny":      {"backend": "ollama", "model": "qwen3:32b", "timeout": 45,  "fallback": "claude", "fallback_model": "claude-haiku-4-5-20251001", "no_think": True},
    "debt_scan":     {"backend": "ollama", "model": "qwen3:32b", "timeout": 90,  "fallback": "claude", "fallback_model": "claude-haiku-4-5-20251001", "no_think": True},
    "summary":       {"backend": "claude", "model": "claude-haiku-4-5-20251001",  "timeout": 120},
    "deep_analysis": {"backend": "claude", "model": "claude-sonnet-4-6",          "timeout": 120},
    "profile":       {"backend": "claude", "model": "claude-sonnet-4-6",          "timeout": 120},
    # 多模态路由 — 仅 Ollama，无 Claude fallback
    "vision":        {"backend": "ollama", "model": "gemma3:27b",                 "timeout": 90},
    "ocr":           {"backend": "ollama", "model": "gemma3:27b",                 "timeout": 90},  # glm-ocr 有兼容性问题，暂用 gemma3
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

        backend = route["backend"]

        # 环境变量强制覆盖
        force_claude = os.environ.get("LLM_FORCE_CLAUDE", "")
        if force_claude and task_type in [t.strip() for t in force_claude.split(",")]:
            backend = "claude"
            log.info(f"router: [force_claude] {task_type} overridden to claude")

        # 编码图片为 base64
        b64_images = self._encode_images(images) if images else None

        if backend == "ollama":
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

    def _ollama_with_fallback(self, prompt: str, task_type: str, route: dict,
                               max_tokens: int, temperature: float,
                               images: list[str] | None = None) -> str:
        """尝试 Ollama，失败则 fallback 到 Claude。"""
        # 启动探测发现 Ollama 不可达 → 直接走 Claude（多模态路由无 fallback）
        if self._ollama_available is False:
            if route.get("fallback"):
                log.info(f"router: [skip_ollama] {task_type} -> claude (ollama unavailable)")
                return self._claude_fallback(prompt, task_type, route, max_tokens)
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
                    return self._claude_fallback(prompt, task_type, route, max_tokens)
                log.warning(f"router: [error] {task_type} ollama_garbage ({len(result.strip())} chars), no fallback")
                return result

            log.info(f"router: [ollama] {task_type} {elapsed:.1f}s ok ({len(result)} chars)")
            return result

        except Exception as e:
            elapsed = time.time() - t0
            reason = type(e).__name__
            if route.get("fallback"):
                log.warning(f"router: [fallback] {task_type} ollama_{reason} ({elapsed:.1f}s) -> claude")
                return self._claude_fallback(prompt, task_type, route, max_tokens)
            log.warning(f"router: [error] {task_type} ollama_{reason} ({elapsed:.1f}s), no fallback")
            return ""

    def _claude_fallback(self, prompt: str, task_type: str, route: dict,
                          max_tokens: int) -> str:
        """Fallback 到 Claude CLI。"""
        fallback_model = route.get("fallback_model", "claude-haiku-4-5-20251001")
        t0 = time.time()
        result = self._claude_generate(prompt, fallback_model, route["timeout"], max_tokens)
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
                          max_tokens: int) -> str:
        """调 Claude CLI（stdin 传 prompt，避免命令行长度限制）。"""
        result = subprocess.run(
            ["claude", "--dangerously-skip-permissions", "--print",
             "--model", model, "-"],
            capture_output=True, text=True,
            timeout=timeout, input=prompt,
        )
        return result.stdout.strip() or result.stderr.strip() or ""

    def check_ollama(self) -> bool:
        """探测 Ollama 是否可达 + 检查所需模型。启动时调用一次。"""
        try:
            url = f"{OLLAMA_HOST}/api/tags"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            models = [m.get("name", "") for m in data.get("models", [])]
            log.info(f"router: Ollama reachable, models: {models}")
            # 检查路由表中需要的模型是否存在
            needed = {r["model"] for r in ROUTES.values() if r["backend"] == "ollama"}
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
