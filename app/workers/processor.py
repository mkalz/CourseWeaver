"""Background job processor.

Orchestrates the complete local pipeline for each queued job:

  1. Moodle → Markdown conversion (ConverterService)
  2. Per-week semantic Markdown chunking (chunk_markdown)
  3. Pedagogical summarisation via Ollama/Qwen (SummariserService)
  4. Accessibility narration rewrite (rewrite_for_accessibility)
  5. TTS synthesis per week (TTSService)
  6. Chapterized MP3 assembly (assemble_chapterized_mp3)
  7. Persist metadata to SQLite (repositories)
  8. Update job status throughout

Failed jobs are retried up to ``settings.job_retry_max_attempts`` times with
exponential back-off. On startup, orphaned ``running`` jobs are re-queued.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.models.audio import AudioSegment
from app.models.course import TextChunk
from app.models.job import Job, JobStatus
from app.repositories.audio_repository import AudioRepository, ChunkRepository
from app.repositories.job_repository import JobRepository
from app.services.accessibility import rewrite_for_accessibility
from app.services.audio_assembler import assemble_chapterized_mp3
from app.services.chunker import chunk_markdown
from app.services.converter import ConverterService
from app.services.summarizer import SummariserService
from app.services.tts import TTSService
from app.workers.queue import JobQueue, get_queue

logger = logging.getLogger(__name__)


class JobProcessor:
    """Processes one job at a time, driven by the shared JobQueue."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._job_repo = JobRepository()
        self._audio_repo = AudioRepository()
        self._chunk_repo = ChunkRepository()
        self._converter = ConverterService()
        self._summariser = SummariserService(settings)
        self._tts = TTSService(settings)

    # ── Worker loop ───────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Consume jobs from the queue indefinitely."""
        queue = get_queue()
        semaphore = asyncio.Semaphore(self._settings.max_concurrent_jobs)
        logger.info(
            "Job processor started (max_concurrent=%d, tts=%s, provider=%s)",
            self._settings.max_concurrent_jobs,
            self._settings.tts_engine,
            self._settings.ai_summary_provider,
        )
        while True:
            job_id = await queue.dequeue()
            asyncio.create_task(self._guarded_process(job_id, semaphore, queue))

    async def _guarded_process(
        self, job_id: str, semaphore: asyncio.Semaphore, queue: JobQueue
    ) -> None:
        async with semaphore:
            try:
                await self._process_job(job_id)
            except Exception as exc:
                logger.exception("Unhandled error processing job %s: %s", job_id, exc)
            finally:
                queue.task_done(job_id)

    # ── Resume orphaned jobs on startup ──────────────────────────────────────

    async def resume_pending_and_orphaned(self) -> None:
        """Re-queue jobs left in pending or running state (e.g. after a crash)."""
        queue = get_queue()
        for status in (JobStatus.running, JobStatus.pending):
            jobs = await self._job_repo.list_by_status(status)
            for job in jobs:
                if queue.is_in_flight(job.id):
                    continue
                if job.attempts >= self._settings.job_retry_max_attempts:
                    await self._job_repo.update_status(
                        job.id,
                        JobStatus.failed,
                        error=f"Exceeded max retry attempts ({job.attempts})",
                    )
                    continue
                logger.info("Re-queueing %s job %s (attempts=%d)", status.value, job.id, job.attempts)
                await self._job_repo.update_status(job.id, JobStatus.pending)
                await queue.enqueue(job.id)

    # ── Pipeline orchestration ────────────────────────────────────────────────

    async def _process_job(self, job_id: str) -> None:
        job = await self._job_repo.get(job_id)
        if job is None:
            logger.warning("Job %s not found in DB; skipping", job_id)
            return

        attempts = await self._job_repo.increment_attempts(job_id)
        await self._job_repo.update_status(job_id, JobStatus.running)
        logger.info("Processing job %s (attempt %d)", job_id, attempts)

        try:
            result = await self._run_pipeline(job)
            await self._job_repo.update_status(
                job_id,
                JobStatus.completed,
                result=result,
                output_dir=result.get("output_dir", ""),
            )
            logger.info("Job %s completed successfully", job_id)

        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc, exc_info=True)
            if attempts < self._settings.job_retry_max_attempts:
                delay = self._settings.job_retry_delay_seconds * (2 ** (attempts - 1))
                logger.info("Scheduling retry for job %s in %.1fs", job_id, delay)
                await asyncio.sleep(delay)
                await self._job_repo.update_status(job_id, JobStatus.pending, error=str(exc))
                await get_queue().enqueue(job_id)
            else:
                await self._job_repo.update_status(
                    job_id, JobStatus.failed, error=str(exc)
                )

    async def _run_pipeline(self, job: Job) -> dict:
        opts = job.options
        s = self._settings

        # ── Step 1: Moodle → Markdown ─────────────────────────────────────────
        logger.info("[job %s] Step 1/6 – Moodle conversion", job.id)
        manifest = await self._converter.convert(
            job.source_dir,
            job.output_dir or None,
            opts.model_dump(),
        )

        audio_dir = Path(s.audio_output_dir) / job.id
        audio_dir.mkdir(parents=True, exist_ok=True)
        chapter_inputs: list[tuple[str, Path]] = []
        audio_segments: list[AudioSegment] = []

        for week in manifest.week_pages:
            logger.info(
                "[job %s] Week %d/%d – %s",
                job.id, week.index, len(manifest.week_pages), week.title,
            )

            # ── Step 2: Semantic chunking ─────────────────────────────────────
            chunks = chunk_markdown(
                week.plain_text,
                max_chars=opts.chunk_max_chars,
                overlap_chars=opts.chunk_overlap_chars,
                min_chars=s.chunk_min_chars,
            )
            logger.debug("[job %s] Week %d: %d chunks", job.id, week.index, len(chunks))

            # ── Step 3: Summarisation ─────────────────────────────────────────
            summary_text = ""
            if chunks:
                summary_text = await self._summariser.summarise_week(
                    chunks, language=opts.ai_summary_language
                )

            # ── Step 4: Accessibility rewrite ─────────────────────────────────
            narration_text = summary_text
            if opts.accessibility_rewrite and summary_text:
                narration_text = rewrite_for_accessibility(
                    summary_text,
                    week_title=week.title,
                    language=opts.ai_summary_language,
                )

            # ── Persist chunks to DB ──────────────────────────────────────────
            db_chunks: list[TextChunk] = []
            for i, chunk in enumerate(chunks):
                tc = TextChunk(
                    job_id=job.id,
                    week_index=week.index,
                    chunk_index=i,
                    heading_path=chunk.heading_path,
                    content=chunk.content,
                    summary=summary_text if i == 0 else "",
                    accessibility_text=narration_text if i == 0 else "",
                )
                db_chunks.append(tc)
            await self._chunk_repo.bulk_save(db_chunks)

            # ── Step 5: TTS synthesis ─────────────────────────────────────────
            audio_path: Path | None = None
            if opts.tts_engine not in {"none", ""} and narration_text:
                try:
                    loop = asyncio.get_running_loop()
                    wav_bytes = await loop.run_in_executor(
                        None, self._tts.synthesise, narration_text
                    )
                    stem = f"{week.index:02d}_{_safe_stem(week.title)}"
                    audio_path = audio_dir / f"{stem}.wav"
                    audio_path.write_bytes(wav_bytes)
                    logger.debug("[job %s] Week %d audio: %s", job.id, week.index, audio_path)
                except Exception as exc:
                    logger.warning(
                        "[job %s] TTS failed for week %d: %s", job.id, week.index, exc
                    )

            # ── Persist audio segment ─────────────────────────────────────────
            seg = AudioSegment(
                job_id=job.id,
                week_index=week.index,
                week_title=week.title,
                audio_path=str(audio_path) if audio_path else "",
                chunk_count=len(chunks),
            )
            await self._audio_repo.save(seg)
            audio_segments.append(seg)

            if audio_path and audio_path.exists():
                chapter_inputs.append((week.title, audio_path))

        # ── Step 6: Chapterized MP3 assembly ──────────────────────────────────
        chapterized_path: str = ""
        if opts.chapterized_mp3 and chapter_inputs:
            logger.info("[job %s] Step 6/6 – assembling chapterized MP3", job.id)
            try:
                mp3_path = audio_dir / "course_chapters.mp3"
                assembled = assemble_chapterized_mp3(
                    chapter_inputs,
                    mp3_path,
                    audio_quality=s.ffmpeg_audio_quality,
                )
                chapterized_path = assembled.output_path
            except Exception as exc:
                logger.warning("[job %s] Chapterized MP3 failed: %s", job.id, exc)

        return {
            "output_dir": manifest.output_dir,
            "weeks_processed": len(manifest.week_pages),
            "audio_segments": len(audio_segments),
            "chapterized_mp3": chapterized_path,
            "tts_engine": opts.tts_engine,
            "ai_provider": s.ai_summary_provider,
        }


def _safe_stem(title: str) -> str:
    import re
    return re.sub(r"[^a-z0-9_-]+", "-", title.lower()).strip("-")[:60] or "week"
