"""
Fish Audio S2 Pro TTS 服务 — SOUL 的声线。
独立进程运行（fish-speech venv），通过 HTTP 提供 TTS 能力。

启动方式：
  cd D:/Agent/fish-speech
  .venv/Scripts/python.exe <orchestrator>/services/tts_server.py

端口：23715

Fish S2 Pro: SOTA 开源 TTS，支持内联情感标签 [laugh] [whisper] 等。
"""
import logging
import os
import sys
import time

import numpy as np
import soundfile as sf
import torch
from flask import Flask, request, jsonify

# Fish Speech 源码路径
FISH_SPEECH_DIR = os.environ.get("FISH_SPEECH_DIR", "D:/Agent/fish-speech")
sys.path.insert(0, FISH_SPEECH_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

_model_manager = None
CHECKPOINT_DIR = os.path.join(FISH_SPEECH_DIR, "checkpoints", "s2-pro")
SAMPLE_RATE = 44100


def get_model_manager():
    global _model_manager
    if _model_manager is None:
        # 禁掉代理
        for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
            os.environ.pop(k, None)

        log.info(f"Loading Fish S2 Pro from {CHECKPOINT_DIR}...")
        from tools.server.model_manager import ModelManager
        _model_manager = ModelManager(
            mode="tts",
            device="cuda" if torch.cuda.is_available() else "cpu",
            half=False,
            compile=False,
            llama_checkpoint_path=CHECKPOINT_DIR,
            decoder_checkpoint_path=os.path.join(CHECKPOINT_DIR, "codec.pth"),
            decoder_config_name="modded_dac_vq",
        )
        log.info(f"Fish S2 Pro loaded on {_model_manager.device}")
    return _model_manager


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "model": "fish-s2-pro",
        "sample_rate": SAMPLE_RATE,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
    })


@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json()
    text = data.get("text", "")
    output = data.get("output", "output.wav")
    temperature = data.get("temperature", 0.8)
    top_p = data.get("top_p", 0.8)
    seed = data.get("seed", None)

    if not text:
        return jsonify({"ok": False, "error": "empty text"})

    try:
        mgr = get_model_manager()
        t0 = time.time()

        from fish_speech.utils.schema import ServeTTSRequest
        req = ServeTTSRequest(
            text=text,
            temperature=temperature,
            top_p=top_p,
            seed=seed,
        )

        segments = []
        sr = SAMPLE_RATE
        for result in mgr.tts_inference_engine.inference(req):
            if result.code == "error":
                return jsonify({"ok": False, "error": str(result.error)})
            if result.code in ("segment", "final") and result.audio is not None:
                sr, wav = result.audio
                segments.append(wav)
                if result.code == "final":
                    break

        if not segments:
            return jsonify({"ok": False, "error": "no audio generated"})

        full_wav = np.concatenate(segments)
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        sf.write(output, full_wav, sr)

        elapsed = time.time() - t0
        duration_s = len(full_wav) / sr

        log.info(f"Generated {duration_s:.1f}s audio in {elapsed:.1f}s -> {output}")
        return jsonify({
            "ok": True,
            "duration_s": round(duration_s, 1),
            "elapsed_s": round(elapsed, 1),
            "sample_rate": sr,
            "output": output,
        })

    except Exception as e:
        log.error(f"TTS error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("TTS_PORT", 23715))
    log.info(f"Starting Fish S2 Pro TTS on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
