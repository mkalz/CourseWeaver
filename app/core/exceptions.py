"""Application-wide exception hierarchy."""
from __future__ import annotations


class CourseWeaverError(Exception):
    """Base error for all application exceptions."""


# ── Conversion ────────────────────────────────────────────────────────────────

class ConversionError(CourseWeaverError):
    """Moodle backup conversion failed."""


class SourceDirectoryNotFound(ConversionError):
    """Source Moodle backup directory does not exist."""


# ── Chunking ──────────────────────────────────────────────────────────────────

class ChunkingError(CourseWeaverError):
    """Semantic chunking of Markdown content failed."""


# ── Summarisation ─────────────────────────────────────────────────────────────

class SummarisationError(CourseWeaverError):
    """LLM summarisation request failed."""


class OllamaUnavailableError(SummarisationError):
    """Ollama endpoint is not reachable."""


# ── TTS ───────────────────────────────────────────────────────────────────────

class TTSError(CourseWeaverError):
    """Text-to-speech synthesis failed."""


class TTSEngineNotAvailable(TTSError):
    """Required TTS library or model files are missing."""


class TTSInputTooLong(TTSError):
    """Input text exceeds the maximum length for the TTS engine."""


# ── Audio assembly ────────────────────────────────────────────────────────────

class AudioAssemblyError(CourseWeaverError):
    """ffmpeg-based audio assembly failed."""


class FfmpegNotFound(AudioAssemblyError):
    """ffmpeg binary is not available on PATH."""


# ── Job management ────────────────────────────────────────────────────────────

class JobNotFound(CourseWeaverError):
    """Requested job ID does not exist in the database."""


class JobAlreadyRunning(CourseWeaverError):
    """Cannot start a job that is already in progress."""


class JobQueueFull(CourseWeaverError):
    """Job queue has reached its capacity limit."""
