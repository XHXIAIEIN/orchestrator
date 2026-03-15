"""
Kokoro TTS 语音合成服务 — SOUL 的声线。
独立进程运行（Python 3.12 venv），通过 HTTP 提供 TTS 能力。

启动方式：D:\Agent\tts-venv\Scripts\python.exe services\tts_server.py
端口：23715

Kokoro: 82M 参数，支持中英日，CPU 就够用。
"""
import logging
import os
import time

import numpy as np
import soundfile as sf
import torch
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# Kokoro pipeline（延迟加载）
_pipeline = None

LOCAL_MODEL_DIR = os.environ.get("KOKORO_MODEL_DIR", "D:/Agent/models/kokoro-82m")
DEFAULT_VOICE = os.environ.get("SOUL_VOICE", "zm_yunxi")
SAMPLE_RATE = 24000


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        # 禁掉代理，避免 huggingface_hub 尝试网络请求
        for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
            os.environ.pop(k, None)

        log.info(f"Loading Kokoro TTS from {LOCAL_MODEL_DIR}...")
        from kokoro import KModel, KPipeline

        model = KModel(
            config=os.path.join(LOCAL_MODEL_DIR, "config.json"),
            model=os.path.join(LOCAL_MODEL_DIR, "kokoro-v1_0.pth"),
        )
        pipe = KPipeline(lang_code="z", model=model, repo_id="hexgrad/Kokoro-82M")

        # Monkey-patch: voice 文件从本地加载而不是走 HF hub
        _orig_load = pipe.load_single_voice
        def _local_load(voice):
            local_path = os.path.join(LOCAL_MODEL_DIR, "voices", f"{voice}.pt")
            if os.path.exists(local_path):
                return torch.load(local_path, map_location="cpu", weights_only=True)
            return _orig_load(voice)
        pipe.load_single_voice = _local_load

        _pipeline = pipe
        log.info(f"Kokoro TTS loaded. Default voice: {DEFAULT_VOICE}")
    return _pipeline


@app.route("/health")
def health():
    return jsonify({"status": "ok", "model": "kokoro", "voice": DEFAULT_VOICE})


@app.route("/voices")
def voices():
    """列出本地已有的 voice presets。"""
    voices_dir = os.path.join(LOCAL_MODEL_DIR, "voices")
    available = []
    if os.path.isdir(voices_dir):
        for f in sorted(os.listdir(voices_dir)):
            if f.endswith(".pt"):
                name = f[:-3]
                lang = {"z": "zh", "a": "en-US", "b": "en-GB", "j": "ja"}.get(name[0], "?")
                gender = "female" if name[1] == "f" else "male"
                available.append({"id": name, "lang": lang, "gender": gender})
    return jsonify({"voices": available})


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

        audio_segments = []
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            if audio is not None:
                audio_segments.append(audio)

        if not audio_segments:
            return jsonify({"ok": False, "error": "no audio generated"})

        wav = np.concatenate(audio_segments)
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
    log.info(f"Starting Kokoro TTS on port {port} (voice: {DEFAULT_VOICE})")
    app.run(host="0.0.0.0", port=port, debug=False)
