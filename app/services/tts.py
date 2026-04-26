"""Local TTS rendering service.

Supports:
  • XTTS v2  (Coqui TTS)  – multilingual, speaker-clonable, GPU-accelerated
  • Kokoro   (kokoro-onnx) – lightweight, fast, CPU-friendly

Both engines are lazily initialised on first use and cached for the lifetime
of the process. GPU detection uses ``torch`` when available.
"""
from __future__ import annotations

import io
import logging
import re
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.core.exceptions import TTSEngineNotAvailable, TTSError, TTSInputTooLong

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

_XTTS_INSTANCE: object | None = None
_KOKORO_INSTANCE: object | None = None

# Maximum characters we send to TTS in one call.
_XTTS_MAX_CHARS = 5000
_KOKORO_MAX_CHARS = 10000


def _get_xtts(model_name: str, device: str):
    """Lazily load and cache the XTTS v2 model."""
    global _XTTS_INSTANCE
    if _XTTS_INSTANCE is not None:
        return _XTTS_INSTANCE
    try:
        from TTS.api import TTS as CoquiTTS
    except ImportError as exc:
        raise TTSEngineNotAvailable(
            "Coqui TTS package not installed. Run: pip install TTS"
        ) from exc
    logger.info("Loading XTTS v2 model (%s) on device=%s …", model_name, device)
    tts = CoquiTTS(model_name)
    if device in {"cuda", "mps"}:
        try:
            tts = tts.to(device)
        except Exception as exc:
            logger.warning("Could not move XTTS to %s: %s — falling back to CPU", device, exc)
    _XTTS_INSTANCE = tts
    return tts


def _get_kokoro(onnx_path: str, voices_path: str):
    """Lazily load and cache the Kokoro ONNX model."""
    global _KOKORO_INSTANCE
    if _KOKORO_INSTANCE is not None:
        return _KOKORO_INSTANCE
    try:
        from kokoro_onnx import Kokoro
    except ImportError as exc:
        raise TTSEngineNotAvailable(
            "kokoro-onnx not installed. Run: pip install kokoro-onnx"
        ) from exc
    if not Path(onnx_path).exists():
        raise TTSEngineNotAvailable(f"Kokoro ONNX model not found: {onnx_path}")
    if not Path(voices_path).exists():
        raise TTSEngineNotAvailable(f"Kokoro voices file not found: {voices_path}")
    logger.info("Loading Kokoro model from %s …", onnx_path)
    _KOKORO_INSTANCE = Kokoro(onnx_path, voices_path)
    return _KOKORO_INSTANCE


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _synthesise_xtts(
    text: str,
    model_name: str,
    device: str,
    voice: str,
    speaker_wav: str,
    language: str,
) -> bytes:
    """Returns raw WAV bytes from XTTS v2."""
    import array as _array
    tts = _get_xtts(model_name, device)
    if len(text) > _XTTS_MAX_CHARS:
        raise TTSInputTooLong(
            f"Input text {len(text)} chars exceeds XTTS limit {_XTTS_MAX_CHARS}. "
            "Split the text before calling synthesise()."
        )
    kwargs: dict = {"text": text, "language": language or "en"}
    if speaker_wav and Path(speaker_wav).exists():
        kwargs["speaker_wav"] = speaker_wav
    elif voice:
        kwargs["speaker"] = voice
    wav_list = tts.tts(**kwargs)
    wav_array = _array.array("h", [int(max(-32768, min(32767, s * 32767))) for s in wav_list])
    return _pcm_to_wav(wav_array.tobytes(), sample_rate=24000)


def _synthesise_kokoro(
    text: str,
    onnx_path: str,
    voices_path: str,
    voice: str,
    language: str,
) -> bytes:
    """Returns raw WAV bytes from Kokoro."""
    import soundfile as sf
    kokoro = _get_kokoro(onnx_path, voices_path)
    if len(text) > _KOKORO_MAX_CHARS:
        raise TTSInputTooLong(
            f"Input text {len(text)} chars exceeds Kokoro limit {_KOKORO_MAX_CHARS}."
        )
    samples, sample_rate = kokoro.create(
        text,
        voice=voice or "af_heart",
        speed=1.0,
        lang=language or "en-us",
    )
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return buf.getvalue()


def _split_for_synthesis(text: str, max_chars: int) -> list[str]:
    """Break *text* into segments ≤ max_chars, splitting at sentence boundaries."""
    if len(text) <= max_chars:
        return [text]
    segments: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            segments.append(remaining)
            break
        cut = remaining.rfind(". ", 0, max_chars)
        if cut == -1:
            cut = remaining.rfind("\n", 0, max_chars)
        if cut == -1:
            cut = max_chars
        segments.append(remaining[:cut + 1].strip())
        remaining = remaining[cut + 1:].strip()
    return [s for s in segments if s]


def _concatenate_wav_bytes(wav_parts: list[bytes]) -> bytes:
    """Concatenate multiple WAV byte strings into one (same format assumed)."""
    if not wav_parts:
        return b""
    if len(wav_parts) == 1:
        return wav_parts[0]
    frames_list: list[bytes] = []
    params = None
    for part in wav_parts:
        with wave.open(io.BytesIO(part), "rb") as wf:
            if params is None:
                params = wf.getparams()
            frames_list.append(wf.readframes(wf.getnframes()))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setparams(params)
        for frames in frames_list:
            wf.writeframes(frames)
    return buf.getvalue()


class TTSService:
    """Unified TTS service. Call ``synthesise()`` with plain text."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = settings.tts_engine.strip().lower()
        self._device = settings.effective_gpu_device()

    def is_enabled(self) -> bool:
        return self._engine not in {"none", ""}

    def synthesise(self, text: str) -> bytes:
        """Synthesise *text* and return WAV bytes.

        Long texts are automatically split and concatenated.
        """
        if not self.is_enabled():
            raise TTSError("TTS engine is set to 'none'")
        text = (text or "").strip()
        if not text:
            raise TTSError("Empty text passed to TTS synthesiser")

        engine = self._engine
        max_chars = _KOKORO_MAX_CHARS if engine == "kokoro" else _XTTS_MAX_CHARS
        segments = _split_for_synthesis(text, max_chars)
        wav_parts: list[bytes] = []

        for seg in segments:
            wav_parts.append(self._synthesise_segment(seg))

        return _concatenate_wav_bytes(wav_parts)

    def _synthesise_segment(self, text: str) -> bytes:
        s = self._settings
        if self._engine == "xtts":
            return _synthesise_xtts(
                text,
                model_name=s.tts_xtts_model,
                device=self._device,
                voice=s.tts_voice,
                speaker_wav=s.tts_speaker_wav,
                language=s.tts_language,
            )
        if self._engine == "kokoro":
            return _synthesise_kokoro(
                text,
                onnx_path=s.tts_kokoro_onnx,
                voices_path=s.tts_kokoro_voices,
                voice=s.tts_voice,
                language=s.tts_language,
            )
        raise TTSError(f"Unknown TTS engine: {self._engine}")
