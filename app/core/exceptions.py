"""Application-wide exception hierarchy."""
from __future__ import annotations


class CourseBeaverError(Exception):
    """Base error for all application exceptions."""


# ── Conversion ────────────────────────────────────────────────────────────────

class ConversionError(CourseBeaverError):
    """Moodle backup conversion failed."""


class SourceDirectoryNotFound(ConversionError):
    """Source Moodle backup directory does not exist."""


# ── Chunking ──────────────────────────────────────────────────────────────────

class ChunkingError(CourseBeaverError):
    """Semantic chunking of Markdown content failed."""


# ── Summarisation ─────────────────────────────────────────────────────────────

class SummarisationError(CourseBeaverError):
    """LLM summarisation request failed."""


class OllamaUnavailableError(SummarisationError):
    """Ollama endpoint is not reachable."""


# ── TTS ───────────────────────────────────────────────────────────────────────

class TTSError(CourseBeaverError):
    """Text-to-speech synthesis failed."""


class TTSEngineNotAvailable(TTSError):
    """Required TTS library or model files are missing."""


class TTSInputTooLong(TTSError):
    """Input text exceeds the maximum length for the TTS engine."""


# ── Audio assembly ────────────────────────────────────────────────────────────

class AudioAssemblyError(CourseBeaverError):
    """ffmpeg-based audio assembly failed."""


class FfmpegNotFound(AudioAssemblyError):
    """ffmpeg binary is not available on PATH."""


# ── Job management ────────────────────────────────────────────────────────────

class JobNotFound(CourseBeaverError):
    """Requested job ID does not exist in the database."""


class JobAlreadyRunning(CourseBeaverError):
    """Cannot start a job that is already in progress."""


class JobQueueFull(CourseBeaverError):
    """Job queue has reached its capacity limit."""
