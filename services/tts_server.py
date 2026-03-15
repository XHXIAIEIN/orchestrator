"""
ChatTTS 语音合成服务 — SOUL 的声线。
独立进程运行（Python 3.12 venv），通过 HTTP 提供 TTS 能力。

启动方式：D:\Agent\tts-venv\Scripts\python.exe services\tts_server.py
端口：23715

ChatTTS: 专为对话设计，自然的停顿、语气、呼吸声。
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

_chat = None

LOCAL_MODEL_DIR = os.environ.get("CHATTTS_MODEL_DIR", "D:/Agent/models/ChatTTS")
SAMPLE_RATE = 24000
# 固定 speaker seed 保证每次生成同一个声音
DEFAULT_SPEAKER_SEED = 42
# 口语化参数 seed
DEFAULT_ORAL_SEED = 7


def get_chat():
    global _chat
    if _chat is None:
        # 禁掉代理
        for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
            os.environ.pop(k, None)

        log.info(f"Loading ChatTTS from {LOCAL_MODEL_DIR}...")
        import ChatTTS
        _chat = ChatTTS.Chat()
        _chat.load(source="custom", custom_path=LOCAL_MODEL_DIR, compile=False)
        log.info("ChatTTS loaded.")
    return _chat


@app.route("/health")
def health():
    return jsonify({"status": "ok", "model": "ChatTTS", "speaker_seed": DEFAULT_SPEAKER_SEED})


@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json()
    text = data.get("text", "")
    output = data.get("output", "output.wav")
    speaker_seed = data.get("speaker_seed", DEFAULT_SPEAKER_SEED)
    oral_seed = data.get("oral_seed", DEFAULT_ORAL_SEED)
    temperature = data.get("temperature", 0.3)
    top_p = data.get("top_p", 0.7)
    top_k = data.get("top_k", 20)

    if not text:
        return jsonify({"ok": False, "error": "empty text"})

    try:
        chat = get_chat()
        t0 = time.time()

        # 固定 speaker 声线
        torch.manual_seed(speaker_seed)
        params_refine = ChatTTS.Chat.RefineTextParams(
            prompt='[oral_2][laugh_0][break_6]',
        )

        params_infer = ChatTTS.Chat.InferCodeParams(
            temperature=temperature,
            top_P=top_p,
            top_K=top_k,
            spk_emb=chat.sample_random_speaker(),
        )

        # 文本优化（加入自然停顿、口语化）
        wavs = chat.infer(
            [text],
            params_refine_text=params_refine,
            params_infer_code=params_infer,
        )

        if wavs is None or len(wavs) == 0:
            return jsonify({"ok": False, "error": "no audio generated"})

        wav = wavs[0]
        if isinstance(wav, torch.Tensor):
            wav = wav.numpy()
        if wav.ndim > 1:
            wav = wav.squeeze()

        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        sf.write(output, wav, SAMPLE_RATE)

        elapsed = time.time() - t0
        duration_s = len(wav) / SAMPLE_RATE

        log.info(f"Generated {duration_s:.1f}s audio in {elapsed:.1f}s (seed={speaker_seed}) -> {output}")
        return jsonify({
            "ok": True,
            "duration_s": round(duration_s, 1),
            "elapsed_s": round(elapsed, 1),
            "speaker_seed": speaker_seed,
            "output": output,
        })

    except Exception as e:
        log.error(f"TTS error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)})


@app.route("/sample_speakers", methods=["POST"])
def sample_speakers():
    """生成多个 speaker seed 的样本，方便选择最合适的声线。"""
    data = request.get_json() or {}
    text = data.get("text", "你好，我是你的 AI 管家。")
    seeds = data.get("seeds", [42, 100, 256, 512, 1024, 2048])
    output_dir = data.get("output_dir", "D:/Agent/tmp/soul-tts/samples")

    os.makedirs(output_dir, exist_ok=True)
    results = []

    chat = get_chat()
    import ChatTTS as CT

    for seed in seeds:
        try:
            torch.manual_seed(seed)
            params = CT.Chat.InferCodeParams(
                temperature=0.3, top_P=0.7, top_K=20,
                spk_emb=chat.sample_random_speaker(),
            )
            wavs = chat.infer([text], params_infer_code=params)
            if wavs and len(wavs) > 0:
                wav = wavs[0]
                if isinstance(wav, torch.Tensor):
                    wav = wav.numpy()
                if wav.ndim > 1:
                    wav = wav.squeeze()
                out = os.path.join(output_dir, f"seed_{seed}.wav")
                sf.write(out, wav, SAMPLE_RATE)
                results.append({"seed": seed, "file": out, "duration_s": round(len(wav)/SAMPLE_RATE, 1)})
        except Exception as e:
            results.append({"seed": seed, "error": str(e)})

    return jsonify({"ok": True, "samples": results})


if __name__ == "__main__":
    port = int(os.environ.get("TTS_PORT", 23715))
    log.info(f"Starting ChatTTS server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
