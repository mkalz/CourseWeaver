"""Job domain models."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    pending   = "pending"
    running   = "running"
    completed = "completed"
    failed    = "failed"
    cancelled = "cancelled"


class JobOptions(BaseModel):
    """All tuneable parameters for one conversion job."""
    # Moodle conversion
    single_page: bool = False
    structured_weeks: bool = True
    week_pages: bool = True
    native_week_pages: bool = False
    pdf_text_blocks: bool = True
    pdf_text_max_pages: int = 8
    pdf_text_max_chars: int = 20000

    # Summarisation
    ai_summary_language: str = "de"
    ai_summary_max_chars: int = 12000

    # Chunking
    chunk_max_chars: int = 8000
    chunk_overlap_chars: int = 200

    # TTS
    tts_engine: str = "xtts"          # "xtts" | "kokoro" | "none"
    tts_voice: str = "af_heart"
    tts_speaker_wav: str = ""
    tts_language: str = "en"

    # Audio assembly
    chapterized_mp3: bool = True

    # Accessibility
    accessibility_rewrite: bool = True

    class Config:
        extra = "ignore"


class JobCreate(BaseModel):
    source_dir: str = Field(..., description="Path to unpacked Moodle backup directory")
    output_dir: str = Field(default="", description="Output directory (auto-generated if blank)")
    options: JobOptions = Field(default_factory=JobOptions)


class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.pending
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_dir: str
    output_dir: str = ""
    options: JobOptions = Field(default_factory=JobOptions)
    result: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0

    # ── Serialisation helpers ─────────────────────────────────────────────────

    def options_json(self) -> str:
        return self.options.model_dump_json()

    def result_json(self) -> str | None:
        return json.dumps(self.result) if self.result is not None else None

    @classmethod
    def from_row(cls, row: Any) -> "Job":
        opts = JobOptions.model_validate_json(row["options"] or "{}")
        result = json.loads(row["result"]) if row["result"] else None
        return cls(
            id=row["id"],
            status=JobStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            source_dir=row["source_dir"],
            output_dir=row["output_dir"] or "",
            options=opts,
            result=result,
            error=row["error"],
            attempts=int(row["attempts"] or 0),
        )


class JobSummary(BaseModel):
    """Lightweight job representation for list responses."""
    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    source_dir: str
    output_dir: str
    attempts: int
    error: str | None = None
