"""
TTS 模块 — SOUL 的声音。
调用 Fish S2 Pro TTS 服务，支持内联情感标签。

用法：
    from src.tts import speak, tag

    # 直接说
    speak("连续第三天凌晨两点还在提交代码。")

    # 带情感标签
    speak(tag("轻松调侃", "你那个 benchmark 到底提了多少，值得你这么拼？"))

    # 混合标签
    text = f"{tag('无奈', '花钱买了不玩，')}{tag('笑', '跟你两百美金一个月养我差不多。')}"
    speak(text)

Fish S2 Pro 支持的情感标签（内联在文本中）：
    [laugh]     笑声
    [whisper]   悄悄话
    [sigh]      叹气
    [轻松]      轻松语气
    [严肃]      严肃语气
    [讽刺]      讽刺语气
    [开心]      开心
    [难过]      难过
    [生气]      生气
    [紧张]      紧张
    [super happy] 非常开心
    自定义中文描述也通常有效。
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


def tag(emotion: str, text: str) -> str:
    """给文本添加情感标签。Fish S2 Pro 会根据标签调整语气。"""
    return f"[{emotion}] {text}"


def speak(text: str, filename: str = "latest.wav",
          temperature: float = 0.8, seed: int | None = None) -> str | None:
    """将文本转为语音，保存到 Dashboard 静态目录。返回 URL 路径或 None。"""
    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        out_path = AUDIO_DIR / filename

        payload = json.dumps({
            "text": text,
            "output": str(out_path),
            "temperature": temperature,
            "seed": seed,
        }).encode()

        req = urllib.request.Request(
            f"{TTS_HOST}/tts",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())

        if data.get("ok"):
            log.info(f"tts: generated {filename} ({data.get('duration_s', '?')}s in {data.get('elapsed_s', '?')}s)")
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
