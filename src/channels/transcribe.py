"""
Audio transcription for channel layer.

Uses faster-whisper (CTranslate2) for local CPU-based speech-to-text.
Converts input audio to WAV via ffmpeg if needed.
"""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# Model size: "tiny" is fastest (~75MB), "base" for better accuracy (~140MB)
_WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "tiny")
_WHISPER_LANG = os.environ.get("WHISPER_LANG", "zh")  # 默认中文，避免 tiny 模型语言检测错误
_model = None


def _get_model():
    """Lazy-load the faster-whisper model (singleton)."""
    global _model
    if _model is not None:
        return _model
    try:
        from faster_whisper import WhisperModel
        log.info(f"transcribe: loading faster-whisper model '{_WHISPER_MODEL}' (CPU)...")
        _model = WhisperModel(_WHISPER_MODEL, device="cpu", compute_type="int8")
        log.info("transcribe: model loaded")
        return _model
    except ImportError:
        log.warning("transcribe: faster-whisper not installed. "
                    "Run: pip install faster-whisper")
        return None
    except Exception as e:
        log.error(f"transcribe: failed to load model: {e}")
        return None


def _find_ffmpeg() -> str:
    """Find ffmpeg binary."""
    # Check PATH first
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    # Known locations on this system
    for candidate in [
        "/d/Program Files/bin/ffmpeg",
        "D:/Program Files/bin/ffmpeg.exe",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return "ffmpeg"  # hope it's on PATH


def _convert_to_wav(input_path: str) -> str:
    """Convert audio file to 16kHz mono WAV for whisper. Returns WAV path."""
    suffix = Path(input_path).suffix.lower()
    if suffix == ".wav":
        return input_path  # already WAV, skip conversion

    wav_path = tempfile.mktemp(suffix=".wav", prefix="transcribe_")
    ffmpeg = _find_ffmpeg()
    cmd = [
        ffmpeg, "-y", "-i", input_path,
        "-ar", "16000",   # 16kHz sample rate
        "-ac", "1",       # mono
        "-c:a", "pcm_s16le",
        wav_path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")[:200]
            log.warning(f"transcribe: ffmpeg conversion failed: {stderr}")
            return ""
        return wav_path
    except FileNotFoundError:
        log.warning("transcribe: ffmpeg not found")
        return ""
    except subprocess.TimeoutExpired:
        log.warning("transcribe: ffmpeg conversion timed out")
        return ""
    except Exception as e:
        log.warning(f"transcribe: ffmpeg error: {e}")
        return ""


def transcribe_audio(file_path: str) -> str:
    """Transcribe an audio file to text.

    Args:
        file_path: Path to audio file (OGG, MP3, WAV, etc.)

    Returns:
        Transcribed text, or empty string on failure.
    """
    if not file_path or not os.path.isfile(file_path):
        log.warning(f"transcribe: file not found: {file_path}")
        return ""

    model = _get_model()
    if model is None:
        return ""

    wav_path = ""
    try:
        # Convert to WAV if needed
        wav_path = _convert_to_wav(file_path)
        if not wav_path:
            return ""

        # Run transcription
        lang = _WHISPER_LANG or None  # None = auto-detect
        segments, info = model.transcribe(
            wav_path,
            beam_size=3,
            vad_filter=True,  # skip silence
            language=lang,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()

        if text:
            lang = info.language
            prob = info.language_probability
            log.info(f"transcribe: [{lang} {prob:.0%}] {text[:80]}{'...' if len(text) > 80 else ''}")
        else:
            log.info("transcribe: no speech detected")

        return text

    except Exception as e:
        log.error(f"transcribe: failed: {e}")
        return ""
    finally:
        # Clean up temp WAV if we created one
        if wav_path and wav_path != file_path:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
