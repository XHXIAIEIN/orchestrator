"""
LLM Backends — Ollama / Claude / Chrome AI 的底层调用函数。
从 llm_router.py 拆分出来，LLMRouter 通过此模块调用各后端。
"""
import base64
import json
import logging
import urllib.request
from pathlib import Path
from typing import Optional

from src.core.llm_models import OLLAMA_HOST

log = logging.getLogger(__name__)


def encode_images(images: list[str]) -> list[str]:
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


def ollama_generate(prompt: str, model: str, timeout: int,
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


def claude_generate(prompt: str, model: str, timeout: int,
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


def chrome_ai_generate(prompt: str, model_id: str, max_tokens: int,
                       _browser_ai_cache: dict = {}) -> Optional[str]:
    """调用 Chrome AI API。需要 BrowserAI 实例可用。

    使用 _browser_ai_cache 字典作为跨调用的懒初始化缓存。
    """
    try:
        from src.core.browser_ai import BrowserAI
        from src.core.browser_runtime import BrowserRuntime
    except ImportError:
        return None

    # 懒初始化 BrowserAI
    if 'instance' not in _browser_ai_cache:
        rt = BrowserRuntime.from_env()
        if not rt.available:
            _browser_ai_cache['instance'] = None
        else:
            _browser_ai_cache['instance'] = BrowserAI(rt)

    browser_ai = _browser_ai_cache['instance']
    if browser_ai is None:
        return None

    ai_type = model_id.split("/", 1)[1]  # "summarizer", "translator", etc.

    if ai_type == "summarizer":
        return browser_ai.summarize_sync(prompt)
    elif ai_type == "translator":
        # 简单处理：prompt 包含翻译指令，直接当摘要用
        return browser_ai.summarize_sync(prompt)
    elif ai_type == "language-detector":
        result = browser_ai.detect_language_sync(prompt)
        if result:
            return json.dumps(result)
        return None
    elif ai_type == "prompt":
        return browser_ai.summarize_sync(prompt)
    else:
        return None
