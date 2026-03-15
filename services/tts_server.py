"""
Fish Audio S2 Pro TTS 服务启动脚本。

直接使用 Fish Speech 官方 API 服务器，无需额外包装。
官方服务器自带 Swagger UI、WebSocket 流式、参考音频管理。

启动方式：
  cd D:/Agent/fish-speech
  .venv/Scripts/python.exe -m tools.api_server \
    --listen 0.0.0.0:23715 \
    --llama-checkpoint-path checkpoints/s2-pro \
    --decoder-checkpoint-path checkpoints/s2-pro/codec.pth \
    --decoder-config-name modded_dac_vq

API 端点：
  POST /v1/tts          — 文本转语音（JSON/msgpack/multipart）
  POST /v1/references/add — 添加参考音频
  GET  /v1/references/list — 列出参考音频
  GET  /v1/health       — 健康检查
  GET  /                — Swagger UI 文档

情感标签语法（圆括号，放句首，最多叠 3 个）：
  (disdainful)(sighing) 连续第三天凌晨两点还在提交代码。
  (sarcastic)(in a hurry tone) 你那个 benchmark 到底提了多少？
  (disappointed)(laugh) 花钱买了不玩，跟你养我差不多。

副语言标签（可放句中任意位置）：
  (break) (long-break) (breath) (laugh) (sigh) (cough)

重要：设置 normalize=false 以保留标签效果。
"""
# 此文件仅作为文档。实际启动使用上面的命令行。
# 如需脚本化启动：

import os
import subprocess
import sys

FISH_DIR = os.environ.get("FISH_SPEECH_DIR", "D:/Agent/fish-speech")
PORT = os.environ.get("TTS_PORT", "23715")

if __name__ == "__main__":
    cmd = [
        os.path.join(FISH_DIR, ".venv", "Scripts", "python.exe"),
        "-m", "tools.api_server",
        "--listen", f"0.0.0.0:{PORT}",
        "--llama-checkpoint-path", os.path.join(FISH_DIR, "checkpoints", "s2-pro"),
        "--decoder-checkpoint-path", os.path.join(FISH_DIR, "checkpoints", "s2-pro", "codec.pth"),
        "--decoder-config-name", "modded_dac_vq",
    ]
    print(f"Starting Fish S2 Pro on port {PORT}...")
    print(f"  Command: {' '.join(cmd)}")
    os.chdir(FISH_DIR)
    os.execv(cmd[0], cmd)
