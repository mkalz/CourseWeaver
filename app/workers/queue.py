"""Async in-process job queue backed by ``asyncio.Queue``."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Coroutine

logger = logging.getLogger(__name__)


class JobQueue:
    """Bounded asyncio queue that distributes job IDs to background workers.

    Usage::

        queue = JobQueue(maxsize=50)
        await queue.enqueue("job-uuid")
        job_id = await queue.dequeue()       # blocks until available
        queue.task_done(job_id)
    """

    def __init__(self, maxsize: int = 50) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._in_flight: set[str] = set()

    # ── Producers ─────────────────────────────────────────────────────────────

    def enqueue_nowait(self, job_id: str) -> None:
        """Non-blocking enqueue; raises ``asyncio.QueueFull`` if capacity exceeded."""
        self._queue.put_nowait(job_id)
        self._in_flight.add(job_id)
        logger.debug("Enqueued job %s (queue size=%d)", job_id, self._queue.qsize())

    async def enqueue(self, job_id: str) -> None:
        """Blocking enqueue; waits if the queue is full."""
        await self._queue.put(job_id)
        self._in_flight.add(job_id)
        logger.debug("Enqueued job %s (queue size=%d)", job_id, self._queue.qsize())

    # ── Consumers ─────────────────────────────────────────────────────────────

    async def dequeue(self) -> str:
        """Block until a job ID is available and return it."""
        job_id = await self._queue.get()
        return job_id

    def task_done(self, job_id: str) -> None:
        """Signal that a dequeued job has been processed."""
        self._in_flight.discard(job_id)
        self._queue.task_done()

    # ── Inspection ────────────────────────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    def is_in_flight(self, job_id: str) -> bool:
        return job_id in self._in_flight


# Module-level singleton – shared between the FastAPI app and background workers.
_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue(maxsize=200)
    return _queue
