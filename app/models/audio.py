"""Audio segment and chapter models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AudioSegment(BaseModel):
    """One synthesised audio file corresponding to a single course week."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    week_index: int
    week_title: str = ""
    audio_path: str = ""            # absolute filesystem path
    duration_seconds: float = 0.0
    chunk_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_row(cls, row: Any) -> "AudioSegment":
        return cls(
            id=row["id"],
            job_id=row["job_id"],
            week_index=int(row["week_index"]),
            week_title=row["week_title"] or "",
            audio_path=row["audio_path"] or "",
            duration_seconds=float(row["duration_seconds"] or 0.0),
            chunk_count=int(row["chunk_count"] or 0),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class ChapterEntry(BaseModel):
    """One chapter entry in the chapterized MP3 metadata."""
    title: str
    audio_path: str
    start_ms: int = 0
    end_ms: int = 0


class ChapterizedAudio(BaseModel):
    """Result of assembling per-week audios into one chapterized MP3."""
    output_path: str
    total_duration_seconds: float
    chapters: list[ChapterEntry] = Field(default_factory=list)
