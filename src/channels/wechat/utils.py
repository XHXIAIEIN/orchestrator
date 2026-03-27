"""WeChat utility functions (standalone, not methods)."""
import logging
import os
import re
import subprocess
import tempfile

log = logging.getLogger(__name__)

WECHAT_MSG_LIMIT = 4000


def _silk_to_wav(silk_buf: bytes) -> bytes | None:
    """Transcode SILK audio to WAV using ffmpeg."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".silk", delete=False) as f:
            f.write(silk_buf)
            silk_path = f.name
        wav_path = silk_path.replace(".silk", ".wav")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                 "-i", silk_path, wav_path],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0 and os.path.exists(wav_path):
                with open(wav_path, "rb") as wf:
                    return wf.read() or None
        finally:
            for p in [silk_path, wav_path]:
                try:
                    os.unlink(p)
                except Exception:
                    pass
    except Exception as e:
        log.debug(f"wechat: silk→wav failed: {e}")
    return None


def _split_message(text: str) -> list[str]:
    limit = WECHAT_MSG_LIMIT
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = text.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def _strip_markdown(text: str) -> str:
    """粗暴去 Markdown，微信不渲染。"""
    text = re.sub(r"```[^\n]*\n?([\s\S]*?)```", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text
