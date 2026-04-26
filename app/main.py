"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import audio, health, jobs
from app.core.config import get_settings
from app.core.database import apply_migrations, configure as configure_db
from app.workers.processor import JobProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

_processor_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _processor_task
    settings = get_settings()

    # ── Bootstrap filesystem + database ──────────────────────────────────────
    for path in (settings.data_dir, settings.audio_output_dir, settings.model_dir):
        Path(path).mkdir(parents=True, exist_ok=True)

    configure_db(settings.db_path)
    await apply_migrations()
    logger.info("Database ready at %s", settings.db_path)

    # ── Start background worker ───────────────────────────────────────────────
    processor = JobProcessor(settings)
    await processor.resume_pending_and_orphaned()
    _processor_task = asyncio.create_task(processor.run_forever(), name="job-processor")
    logger.info(
        "CourseWeaver API started  —  TTS=%s  provider=%s  device=%s",
        settings.tts_engine,
        settings.ai_summary_provider,
        settings.effective_gpu_device(),
    )

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    if _processor_task and not _processor_task.done():
        _processor_task.cancel()
        try:
            await _processor_task
        except asyncio.CancelledError:
            pass
    logger.info("CourseWeaver API shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CourseWeaver",
        summary="Accessibility-optimised narrated audio from Moodle course content",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(audio.router)

    return app


app = create_app()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="CourseWeaver API server")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload or settings.debug,
        log_level="info",
    )


if __name__ == "__main__":
    main()
