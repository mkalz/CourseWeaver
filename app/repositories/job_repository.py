"""SQLite-backed job repository."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core.database import get_connection
from app.models.job import Job, JobStatus, JobSummary
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):

    async def get(self, id: str) -> Job | None:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (id,)
            ) as cursor:
                row = await cursor.fetchone()
                return Job.from_row(row) if row else None

    async def list(self, limit: int = 100, offset: int = 0) -> list[JobSummary]:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT id, status, created_at, updated_at, source_dir, output_dir, attempts, error "
                "FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    JobSummary(
                        id=r["id"],
                        status=JobStatus(r["status"]),
                        created_at=datetime.fromisoformat(r["created_at"]),
                        updated_at=datetime.fromisoformat(r["updated_at"]),
                        source_dir=r["source_dir"],
                        output_dir=r["output_dir"] or "",
                        attempts=int(r["attempts"] or 0),
                        error=r["error"],
                    )
                    for r in rows
                ]

    async def list_by_status(self, status: JobStatus) -> list[Job]:
        async with get_connection() as conn:
            async with conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC",
                (status.value,),
            ) as cursor:
                rows = await cursor.fetchall()
                return [Job.from_row(r) for r in rows]

    async def save(self, job: Job) -> Job:
        job.updated_at = datetime.now(timezone.utc)
        async with get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO jobs (id, status, created_at, updated_at, source_dir, output_dir, options, result, error, attempts)
                VALUES (:id, :status, :created_at, :updated_at, :source_dir, :output_dir, :options, :result, :error, :attempts)
                ON CONFLICT(id) DO UPDATE SET
                    status     = excluded.status,
                    updated_at = excluded.updated_at,
                    output_dir = excluded.output_dir,
                    options    = excluded.options,
                    result     = excluded.result,
                    error      = excluded.error,
                    attempts   = excluded.attempts
                """,
                {
                    "id":         job.id,
                    "status":     job.status.value,
                    "created_at": job.created_at.isoformat(),
                    "updated_at": job.updated_at.isoformat(),
                    "source_dir": job.source_dir,
                    "output_dir": job.output_dir,
                    "options":    job.options_json(),
                    "result":     job.result_json(),
                    "error":      job.error,
                    "attempts":   job.attempts,
                },
            )
            await conn.commit()
        return job

    async def update_status(
        self,
        id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        result: dict | None = None,
        output_dir: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status=?, updated_at=?, error=?, result=?, output_dir=COALESCE(?, output_dir) WHERE id=?",
                (
                    status.value,
                    now,
                    error,
                    json.dumps(result) if result is not None else None,
                    output_dir,
                    id,
                ),
            )
            await conn.commit()

    async def increment_attempts(self, id: str) -> int:
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE jobs SET attempts = attempts + 1, updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), id),
            )
            await conn.commit()
            async with conn.execute(
                "SELECT attempts FROM jobs WHERE id = ?", (id,)
            ) as cur:
                row = await cur.fetchone()
                return int(row["attempts"]) if row else 0

    async def delete(self, id: str) -> bool:
        async with get_connection() as conn:
            cursor = await conn.execute("DELETE FROM jobs WHERE id = ?", (id,))
            await conn.commit()
            return cursor.rowcount > 0
