"""Async SQLite database setup using aiosqlite."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite

logger = logging.getLogger(__name__)

_DB_PATH: Path | None = None


def configure(db_path: Path) -> None:
    global _DB_PATH
    _DB_PATH = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def get_connection() -> AsyncGenerator[aiosqlite.Connection, None]:
    if _DB_PATH is None:
        raise RuntimeError("Database not configured. Call configure() first.")
    async with aiosqlite.connect(str(_DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        yield conn


async def apply_migrations() -> None:
    """Idempotent schema bootstrap – safe to run on every startup."""
    async with get_connection() as conn:
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id            TEXT    PRIMARY KEY,
                status        TEXT    NOT NULL DEFAULT 'pending',
                created_at    TEXT    NOT NULL,
                updated_at    TEXT    NOT NULL,
                source_dir    TEXT    NOT NULL,
                output_dir    TEXT    NOT NULL DEFAULT '',
                options       TEXT    NOT NULL DEFAULT '{}',
                result        TEXT,
                error         TEXT,
                attempts      INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

            CREATE TABLE IF NOT EXISTS audio_segments (
                id               TEXT    PRIMARY KEY,
                job_id           TEXT    NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                week_index       INTEGER NOT NULL,
                week_title       TEXT    NOT NULL DEFAULT '',
                audio_path       TEXT    NOT NULL DEFAULT '',
                duration_seconds REAL    NOT NULL DEFAULT 0.0,
                chunk_count      INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_audio_job ON audio_segments(job_id);

            CREATE TABLE IF NOT EXISTS chunks (
                id                  TEXT    PRIMARY KEY,
                job_id              TEXT    NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                week_index          INTEGER NOT NULL,
                chunk_index         INTEGER NOT NULL,
                heading_path        TEXT    NOT NULL DEFAULT '',
                content             TEXT    NOT NULL DEFAULT '',
                summary             TEXT    NOT NULL DEFAULT '',
                accessibility_text  TEXT    NOT NULL DEFAULT '',
                created_at          TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_job ON chunks(job_id, week_index);
            """
        )
        await conn.commit()
    logger.info("Database migrations applied.")
