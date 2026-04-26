"""FastAPI dependency providers (dependency injection layer)."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.repositories.audio_repository import AudioRepository, ChunkRepository
from app.repositories.job_repository import JobRepository
from app.services.converter import ConverterService
from app.services.summarizer import SummariserService
from app.services.tts import TTSService
from app.workers.queue import JobQueue, get_queue


# ── Settings ──────────────────────────────────────────────────────────────────

def _get_settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(_get_settings)]


# ── Repositories ──────────────────────────────────────────────────────────────

def _job_repo() -> JobRepository:
    return JobRepository()


def _audio_repo() -> AudioRepository:
    return AudioRepository()


def _chunk_repo() -> ChunkRepository:
    return ChunkRepository()


JobRepoDep   = Annotated[JobRepository,   Depends(_job_repo)]
AudioRepoDep = Annotated[AudioRepository, Depends(_audio_repo)]
ChunkRepoDep = Annotated[ChunkRepository, Depends(_chunk_repo)]


# ── Services ──────────────────────────────────────────────────────────────────

def _summariser(settings: SettingsDep) -> SummariserService:
    return SummariserService(settings)


def _tts(settings: SettingsDep) -> TTSService:
    return TTSService(settings)


def _converter() -> ConverterService:
    return ConverterService()


SummariserDep = Annotated[SummariserService, Depends(_summariser)]
TTSDep        = Annotated[TTSService,        Depends(_tts)]
ConverterDep  = Annotated[ConverterService,  Depends(_converter)]


# ── Job queue ─────────────────────────────────────────────────────────────────

def _queue() -> JobQueue:
    return get_queue()


QueueDep = Annotated[JobQueue, Depends(_queue)]
