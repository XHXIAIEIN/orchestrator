"""
TTS 模块 — SOUL 的声音。
调用独立的 ChatTTS 服务（Python 3.12 环境），生成管家风格的语音。
"""
import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path

log = logging.getLogger(__name__)

TTS_HOST = os.environ.get("TTS_HOST", "http://localhost:23715")
AUDIO_DIR = Path(os.environ.get("ORCHESTRATOR_ROOT", ".")) / "dashboard" / "public" / "audio"


def speak(text: str, filename: str = "latest.wav") -> str | None:
    """将文本转为语音，保存到 Dashboard 静态目录。返回 URL 路径或 None。"""
    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        out_path = AUDIO_DIR / filename

        payload = json.dumps({
            "text": text,
            "output": str(out_path),
        }).encode()

        req = urllib.request.Request(
            f"{TTS_HOST}/tts",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())

        if data.get("ok"):
            log.info(f"tts: generated {filename} ({data.get('duration_s', '?')}s)")
            return f"/audio/{filename}"
        else:
            log.warning(f"tts: generation failed: {data.get('error', 'unknown')}")
            return None

    except (urllib.error.URLError, Exception) as e:
        log.warning(f"tts: service unreachable ({e})")
        return None


def is_available() -> bool:
    """检查 TTS 服务是否在线。"""
    try:
        with urllib.request.urlopen(f"{TTS_HOST}/health", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False
