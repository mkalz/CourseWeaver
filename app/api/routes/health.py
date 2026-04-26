"""Health check and runtime info endpoint."""
from __future__ import annotations

import platform
import sys
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter

from app.api.dependencies import QueueDep, SettingsDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Health check")
async def health(settings: SettingsDep, queue: QueueDep) -> dict[str, Any]:
    gpu_device = settings.effective_gpu_device()

    # Probe Ollama reachability.
    ollama_status = "unknown"
    if settings.ai_summary_provider == "local":
        try:
            ollama_url = settings.ollama_base_url.replace("/v1", "").rstrip("/")
            host = (urlparse(ollama_url).hostname or "").lower()
            trust_env = host not in {"127.0.0.1", "localhost"}
            async with httpx.AsyncClient(timeout=3, trust_env=trust_env) as client:
                resp = await client.get(ollama_url + "/api/tags")
                ollama_status = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as exc:
            ollama_status = f"unreachable ({exc.__class__.__name__})"

    return {
        "status": "ok",
        "python": sys.version,
        "platform": platform.platform(),
        "gpu_device": gpu_device,
        "tts_engine": settings.tts_engine,
        "ai_provider": settings.ai_summary_provider,
        "ollama_model": settings.ollama_model,
        "ollama_status": ollama_status,
        "queue_pending": queue.pending_count,
        "queue_in_flight": queue.in_flight_count,
        "max_concurrent_jobs": settings.max_concurrent_jobs,
    }
