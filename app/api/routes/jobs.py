"""Job management REST endpoints.

  POST   /api/jobs               – create and enqueue a new job
  GET    /api/jobs               – list all jobs (paginated)
  GET    /api/jobs/{id}          – get job detail
  DELETE /api/jobs/{id}          – cancel / delete a job
  POST   /api/jobs/{id}/retry    – re-enqueue a failed job
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.api.dependencies import JobRepoDep, QueueDep, SettingsDep
from app.core.exceptions import JobNotFound, JobQueueFull
from app.models.job import Job, JobCreate, JobStatus, JobSummary

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", status_code=202, summary="Submit a new conversion job")
async def create_job(
    body: JobCreate,
    job_repo: JobRepoDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    job = Job(
        source_dir=body.source_dir,
        output_dir=body.output_dir or "",
        options=body.options,
    )
    await job_repo.save(job)
    try:
        await queue.enqueue(job.id)
    except Exception as exc:
        await job_repo.update_status(job.id, JobStatus.failed, error=str(exc))
        raise HTTPException(status_code=503, detail=f"Job queue unavailable: {exc}")

    return {"id": job.id, "status": job.status, "message": "Job accepted"}


@router.get("", summary="List jobs")
async def list_jobs(
    job_repo: JobRepoDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[JobSummary]:
    return await job_repo.list(limit=limit, offset=offset)


@router.get("/{job_id}", summary="Get job details")
async def get_job(job_id: str, job_repo: JobRepoDep) -> Job:
    job = await job_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    return job


@router.delete("/{job_id}", summary="Cancel / delete a job")
async def delete_job(job_id: str, job_repo: JobRepoDep) -> dict[str, str]:
    job = await job_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    if job.status == JobStatus.running:
        raise HTTPException(
            status_code=409, detail="Cannot delete a running job. Wait for completion."
        )
    await job_repo.delete(job_id)
    return {"status": "deleted"}


@router.post("/{job_id}/retry", status_code=202, summary="Re-enqueue a failed job")
async def retry_job(
    job_id: str,
    job_repo: JobRepoDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    job = await job_repo.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    if job.status == JobStatus.running:
        raise HTTPException(status_code=409, detail="Job is already running")
    if job.status not in {JobStatus.failed, JobStatus.cancelled}:
        raise HTTPException(
            status_code=422,
            detail=f"Only failed or cancelled jobs can be retried (status={job.status})",
        )
    await job_repo.update_status(job_id, JobStatus.pending, error=None)
    await queue.enqueue(job_id)
    return {"id": job_id, "status": "pending", "message": "Job re-queued"}
