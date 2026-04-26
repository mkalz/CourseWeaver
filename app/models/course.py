"""Course, week, and chunk domain models."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


class TextChunk(BaseModel):
    """One semantically coherent piece of a week's Markdown content."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    week_index: int
    chunk_index: int
    heading_path: str = ""          # e.g. "Week 3 > Resources > Reading"
    content: str = ""               # original Markdown text of this chunk
    summary: str = ""               # LLM-generated pedagogical summary
    accessibility_text: str = ""    # accessibility-rewritten narration text
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_row(cls, row: Any) -> "TextChunk":
        return cls(
            id=row["id"],
            job_id=row["job_id"],
            week_index=int(row["week_index"]),
            chunk_index=int(row["chunk_index"]),
            heading_path=row["heading_path"] or "",
            content=row["content"] or "",
            summary=row["summary"] or "",
            accessibility_text=row["accessibility_text"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class WeekPage(BaseModel):
    """Represents one week / section exported from Moodle."""
    index: int
    title: str = ""
    relative_path: str = ""         # path relative to output_dir
    plain_text: str = ""            # plain text extracted from Markdown


class CourseManifest(BaseModel):
    """Metadata returned by the Moodle converter."""
    output_dir: str
    week_pages: list[WeekPage] = Field(default_factory=list)
    raw_result: dict = Field(default_factory=dict)
