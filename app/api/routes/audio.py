"""Audio serving and download endpoints.

  GET  /api/audio/{job_id}               – list audio segments for a job
  GET  /api/audio/{job_id}/{segment_id}  – download one segment WAV
  GET  /api/audio/{job_id}/chapters.mp3  – download chapterized MP3
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.dependencies import AudioRepoDep, JobRepoDep
from app.models.audio import AudioSegment

router = APIRouter(prefix="/api/audio", tags=["audio"])


@router.get("/{job_id}", summary="List audio segments for a job")
async def list_segments(
    job_id: str,
    job_repo: JobRepoDep,
    audio_repo: AudioRepoDep,
) -> list[AudioSegment]:
    job = await job_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return await audio_repo.list_for_job(job_id)


@router.get(
    "/{job_id}/{segment_id}",
    summary="Download a single week audio segment (WAV)",
    response_class=FileResponse,
)
async def download_segment(
    job_id: str,
    segment_id: str,
    audio_repo: AudioRepoDep,
) -> FileResponse:
    seg = await audio_repo.get(segment_id)
    if seg is None or seg.job_id != job_id:
        raise HTTPException(status_code=404, detail="Audio segment not found")
    path = Path(seg.audio_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not on disk")
    return FileResponse(
        path=str(path),
        media_type="audio/wav",
        filename=path.name,
    )


@router.get(
    "/{job_id}/chapters.mp3",
    summary="Download the chapterized MP3 for a job",
    response_class=FileResponse,
)
async def download_chapters_mp3(
    job_id: str,
    job_repo: JobRepoDep,
) -> FileResponse:
    job = await job_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    result = job.result or {}
    mp3_path_str = result.get("chapterized_mp3", "")
    if not mp3_path_str:
        raise HTTPException(status_code=404, detail="No chapterized MP3 for this job")
    mp3_path = Path(mp3_path_str)
    if not mp3_path.exists():
        raise HTTPException(status_code=404, detail="MP3 file not on disk")
    return FileResponse(
        path=str(mp3_path),
        media_type="audio/mpeg",
        filename=mp3_path.name,
    )
