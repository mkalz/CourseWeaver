"""Application settings loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8766
    debug: bool = False
    cors_origins: list[str] = Field(
        default=["http://localhost:8766", "http://127.0.0.1:8766"]
    )

    # ── Filesystem paths ──────────────────────────────────────────────────────
    data_dir: Path = Path("data")
    db_path: Path = Path("data/coursebeaver.db")
    audio_output_dir: Path = Path("data/audio")
    model_dir: Path = Path("data/models")

    # ── Ollama / local LLM ────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:14b"
    local_llm_max_tokens: int = 600
    local_llm_temperature: float = 0.3
    local_llm_timeout_seconds: int = 300

    # ── Semantic chunking ─────────────────────────────────────────────────────
    chunk_max_chars: int = 8000
    chunk_overlap_chars: int = 200
    chunk_min_chars: int = 100

    # ── TTS ───────────────────────────────────────────────────────────────────
    tts_engine: str = "xtts"          # "xtts" | "kokoro" | "none"
    tts_xtts_model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    tts_kokoro_onnx: str = "data/models/kokoro/kokoro-v1.0.onnx"
    tts_kokoro_voices: str = "data/models/kokoro/voices.bin"
    tts_voice: str = "af_heart"       # Kokoro voice name or XTTS speaker name
    tts_speaker_wav: str = ""         # XTTS speaker-cloning WAV path (optional)
    tts_language: str = "en"
    tts_sample_rate: int = 24000
    use_gpu: bool = True              # auto-detected; set False to force CPU

    # ── Audio assembly ────────────────────────────────────────────────────────
    ffmpeg_audio_quality: str = "4"   # libmp3lame -q:a value (2=best, 9=worst)

    # ── Job queue ─────────────────────────────────────────────────────────────
    max_concurrent_jobs: int = 2
    job_retry_max_attempts: int = 3
    job_retry_delay_seconds: float = 5.0

    # ── Cloud API keys (optional, for hybrid mode) ────────────────────────────
    openai_api_key: str = ""
    gemini_api_key: str = ""
    google_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    ai_summary_provider: str = "local"   # "local" | "openai" | "gemini"
    ai_summary_model: str = ""           # overrides ollama_model when non-local
    ai_summary_base_url: str = ""        # overrides ollama_base_url when non-local

    def model_post_init(self, __context: object) -> None:
        """Prefer the new DB name and transparently fall back to legacy data."""
        default_db = self.data_dir / "coursebeaver.db"
        legacy_db = self.data_dir / "courseweaver.db"
        if self.db_path == default_db and (not default_db.exists()) and legacy_db.exists():
            self.db_path = legacy_db

    def effective_gpu_device(self) -> str:
        """Return 'cuda', 'mps', or 'cpu' based on availability and config."""
        if not self.use_gpu:
            return "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass
        return "cpu"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
