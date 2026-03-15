"""
Kokoro TTS 语音合成服务 — SOUL 的声线。
独立进程运行（Python 3.12 venv），通过 HTTP 提供 TTS 能力。

启动方式：D:\Agent\tts-venv\Scripts\python.exe services\tts_server.py
端口：23715

Kokoro: 82M 参数，支持中英日，CPU 就够用。
中文语音使用 'zf_xiaobei' 或 'zf_xiaoni' 等 voice preset。
"""
import logging
import os
import time

import numpy as np
import soundfile as sf
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# Kokoro pipeline（延迟加载）
_pipeline = None

# 中文 voice presets（Kokoro 内置）
# zf = 中文女声, zm = 中文男声
DEFAULT_VOICE = "zf_xiaobei"
SAMPLE_RATE = 24000


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        log.info("Loading Kokoro TTS model (first request)...")
        from kokoro import KPipeline
        _pipeline = KPipeline(lang_code="z")  # z = 中文
        log.info("Kokoro TTS model loaded.")
    return _pipeline


@app.route("/health")
def health():
    return jsonify({"status": "ok", "model": "kokoro", "voice": DEFAULT_VOICE})


@app.route("/voices")
def voices():
    """列出可用的 voice presets。"""
    # Kokoro 中文 voices
    zh_voices = [
        {"id": "zf_xiaobei", "lang": "zh", "gender": "female", "desc": "小北 — 活泼"},
        {"id": "zf_xiaoni", "lang": "zh", "gender": "female", "desc": "小妮 — 温柔"},
        {"id": "zf_xiaoxuan", "lang": "zh", "gender": "female", "desc": "小萱 — 甜美"},
        {"id": "zm_yunjian", "lang": "zh", "gender": "male", "desc": "云健 — 沉稳"},
        {"id": "zm_yunxi", "lang": "zh", "gender": "male", "desc": "云希 — 青年"},
        {"id": "zm_yunyang", "lang": "zh", "gender": "male", "desc": "云扬 — 新闻"},
    ]
    return jsonify({"voices": zh_voices})


@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json()
    text = data.get("text", "")
    output = data.get("output", "output.wav")
    voice = data.get("voice", DEFAULT_VOICE)
    speed = data.get("speed", 1.0)

    if not text:
        return jsonify({"ok": False, "error": "empty text"})

    try:
        pipeline = get_pipeline()
        t0 = time.time()

        # Kokoro 生成语音
        audio_segments = []
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            if audio is not None:
                audio_segments.append(audio)

        if not audio_segments:
            return jsonify({"ok": False, "error": "no audio generated"})

        # 拼接所有段落
        wav = np.concatenate(audio_segments)

        # 确保输出目录存在
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        sf.write(output, wav, SAMPLE_RATE)

        elapsed = time.time() - t0
        duration_s = len(wav) / SAMPLE_RATE

        log.info(f"Generated {duration_s:.1f}s audio in {elapsed:.1f}s (voice={voice}, speed={speed}) -> {output}")
        return jsonify({
            "ok": True,
            "duration_s": round(duration_s, 1),
            "elapsed_s": round(elapsed, 1),
            "voice": voice,
            "output": output,
        })

    except Exception as e:
        log.error(f"TTS error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("TTS_PORT", 23715))
    log.info(f"Starting Kokoro TTS server on port {port}")
    log.info(f"Default voice: {DEFAULT_VOICE}")
    log.info("First request will trigger model loading")
    app.run(host="0.0.0.0", port=port, debug=False)
