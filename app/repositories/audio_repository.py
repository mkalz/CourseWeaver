"""SQLite-backed repositories for audio segments and chunks."""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.database import get_connection
from app.models.audio import AudioSegment
from app.models.course import TextChunk
from app.repositories.base import BaseRepository


class AudioRepository(BaseRepository[AudioSegment]):

    async def get(self, id: str) -> AudioSegment | None:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM audio_segments WHERE id = ?", (id,)
            ) as cur:
                row = await cur.fetchone()
                return AudioSegment.from_row(row) if row else None

    async def list(self, limit: int = 100, offset: int = 0) -> list[AudioSegment]:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM audio_segments ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ) as cur:
                return [AudioSegment.from_row(r) for r in await cur.fetchall()]

    async def list_for_job(self, job_id: str) -> list[AudioSegment]:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM audio_segments WHERE job_id = ? ORDER BY week_index ASC",
                (job_id,),
            ) as cur:
                return [AudioSegment.from_row(r) for r in await cur.fetchall()]

    async def save(self, seg: AudioSegment) -> AudioSegment:
        async with get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO audio_segments
                    (id, job_id, week_index, week_title, audio_path, duration_seconds, chunk_count, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    audio_path       = excluded.audio_path,
                    duration_seconds = excluded.duration_seconds,
                    chunk_count      = excluded.chunk_count
                """,
                (
                    seg.id, seg.job_id, seg.week_index, seg.week_title,
                    seg.audio_path, seg.duration_seconds, seg.chunk_count,
                    seg.created_at.isoformat(),
                ),
            )
            await conn.commit()
        return seg

    async def delete(self, id: str) -> bool:
        async with get_connection() as conn:
            cur = await conn.execute(
                "DELETE FROM audio_segments WHERE id = ?", (id,)
            )
            await conn.commit()
            return cur.rowcount > 0

    async def delete_for_job(self, job_id: str) -> int:
        async with get_connection() as conn:
            cur = await conn.execute(
                "DELETE FROM audio_segments WHERE job_id = ?", (job_id,)
            )
            await conn.commit()
            return cur.rowcount


class ChunkRepository(BaseRepository[TextChunk]):

    async def get(self, id: str) -> TextChunk | None:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM chunks WHERE id = ?", (id,)
            ) as cur:
                row = await cur.fetchone()
                return TextChunk.from_row(row) if row else None

    async def list(self, limit: int = 100, offset: int = 0) -> list[TextChunk]:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM chunks LIMIT ? OFFSET ?", (limit, offset)
            ) as cur:
                return [TextChunk.from_row(r) for r in await cur.fetchall()]

    async def list_for_week(self, job_id: str, week_index: int) -> list[TextChunk]:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM chunks WHERE job_id=? AND week_index=? ORDER BY chunk_index ASC",
                (job_id, week_index),
            ) as cur:
                return [TextChunk.from_row(r) for r in await cur.fetchall()]

    async def save(self, chunk: TextChunk) -> TextChunk:
        async with get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO chunks
                    (id, job_id, week_index, chunk_index, heading_path, content,
                     summary, accessibility_text, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    summary            = excluded.summary,
                    accessibility_text = excluded.accessibility_text
                """,
                (
                    chunk.id, chunk.job_id, chunk.week_index, chunk.chunk_index,
                    chunk.heading_path, chunk.content, chunk.summary,
                    chunk.accessibility_text, chunk.created_at.isoformat(),
                ),
            )
            await conn.commit()
        return chunk

    async def delete(self, id: str) -> bool:
        async with get_connection() as conn:
            cur = await conn.execute("DELETE FROM chunks WHERE id = ?", (id,))
            await conn.commit()
            return cur.rowcount > 0

    async def bulk_save(self, chunks: list[TextChunk]) -> None:
        if not chunks:
            return
        async with get_connection() as conn:
            await conn.executemany(
                """
                INSERT INTO chunks
                    (id, job_id, week_index, chunk_index, heading_path, content,
                     summary, accessibility_text, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    summary            = excluded.summary,
                    accessibility_text = excluded.accessibility_text
                """,
                [
                    (
                        c.id, c.job_id, c.week_index, c.chunk_index,
                        c.heading_path, c.content, c.summary,
                        c.accessibility_text, c.created_at.isoformat(),
                    )
                    for c in chunks
                ],
            )
            await conn.commit()
