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

Fish S2 Pro 控制语法：方括号 [tag]，可放文本任意位置，支持自然语言描述。

    情感/风格标签：
        [angry] [excited] [sad] [surprised] [calm] [whisper] [emphasis]

    副语言标签：
        [laugh] [sigh] [gasp] [pause] [cough]

    自然语言描述（S2 Pro 的核心能力）：
        [speaking slowly, with disappointment]
        [whispering nervously]
        [laughing while speaking]
        [快速吐槽，带点不耐烦]

    使用示例：
        [disappointed] 连续第三天凌晨两点还在提交代码。
        你那个 benchmark 到底提了多少 [emphasis] 值得你这么拼？
        花钱买了不玩 [laugh] 跟你两百美金一个月养我差不多。
        [speaking with casual sarcasm] Steam 四十四个游戏，最近游玩时间四十七天前。

    注意：设置 normalize=False 以保留标签效果。
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
    """给文本添加情感标签。方括号语法，可放任意位置。支持自然语言描述。"""
    return f"[{emotion}] {text}"


def sfx(effect: str) -> str:
    """副语言标签（可放句中任意位置）：laugh, whisper, sigh, gasp, pause, emphasis。"""
    return f"[{effect}]"


def speak(text: str, filename: str = "latest.wav",
          temperature: float = 0.8, seed: int | None = None,
          reference_id: str | None = None) -> str | None:
    """将文本转为语音，保存到 Dashboard 静态目录。返回 URL 路径或 None。

    调用 Fish Speech 官方 API（/v1/tts），返回 wav 音频流。
    """
    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        out_path = AUDIO_DIR / filename

        body = {
            "text": text,
            "temperature": temperature,
            "normalize": False,  # 保留情感标签效果
            "format": "wav",
        }
        if seed is not None:
            body["seed"] = seed
        if reference_id:
            body["reference_id"] = reference_id

        payload = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{TTS_HOST}/v1/tts",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            audio_data = resp.read()

        if len(audio_data) > 100:  # 有效音频数据
            out_path.write_bytes(audio_data)
            # 音量归一化（参考音频克隆时音量偏小）
            _normalize_volume(out_path)
            log.info(f"tts: generated {filename} ({len(audio_data)/1024:.0f} KB)")
            return f"/audio/{filename}"
        else:
            log.warning(f"tts: empty audio response ({len(audio_data)} bytes)")
            return None

    except (urllib.error.URLError, Exception) as e:
        log.warning(f"tts: service unreachable ({e})")
        return None


def _normalize_volume(wav_path: Path, target_db: float = -3.0):
    """将 wav 文件音量归一化到目标 dB。解决参考音频克隆时音量偏小的问题。"""
    try:
        import wave
        import struct
        import math

        with wave.open(str(wav_path), 'rb') as wf:
            params = wf.getparams()
            frames = wf.readframes(params.nframes)

        # 解码为 float
        fmt = f"<{params.nframes * params.nchannels}h"
        samples = list(struct.unpack(fmt, frames))

        if not samples:
            return

        # 计算当前峰值
        peak = max(abs(s) for s in samples) or 1
        # 目标峰值（-3dB = 0.708 of max）
        target_peak = 32767 * (10 ** (target_db / 20))
        gain = target_peak / peak

        # 应用增益
        normalized = [max(-32768, min(32767, int(s * gain))) for s in samples]

        with wave.open(str(wav_path), 'wb') as wf:
            wf.setparams(params)
            wf.writeframes(struct.pack(fmt, *normalized))

    except Exception as e:
        log.warning(f"tts: volume normalization failed: {e}")


def is_available() -> bool:
    """检查 TTS 服务是否在线。"""
    try:
        with urllib.request.urlopen(f"{TTS_HOST}/v1/health", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False
