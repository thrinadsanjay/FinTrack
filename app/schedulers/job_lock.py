"""
Cross-process singleton guard for scheduled jobs.

Every web worker/replica runs its own APScheduler. Wrapping a job with
@singleton_job makes the processes race for a lease document in
`scheduler_locks`; only the holder runs, the others skip that tick.
A crashed holder's lease simply expires.

FT_SCHEDULER_LOCKS=off disables the guard (single-process setups, tests).
"""

from __future__ import annotations

import functools
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, TypeVar

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db import mongo

logger = logging.getLogger(__name__)

T = TypeVar("T")
HOST = socket.gethostname()


def _locks_enabled() -> bool:
    return str(os.getenv("FT_SCHEDULER_LOCKS", "on")).strip().lower() not in ("off", "false", "0", "no")


async def acquire_lease(job_id: str, lease_seconds: float) -> str | None:
    """Return a lease token if this caller now owns job_id, else None."""
    now = datetime.now(timezone.utc)
    token = f"{HOST}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
    try:
        doc = await mongo.db.scheduler_locks.find_one_and_update(
            {"_id": job_id, "expires_at": {"$lte": now}},
            {
                "$set": {
                    "token": token,
                    "host": HOST,
                    "acquired_at": now,
                    "expires_at": now + timedelta(seconds=lease_seconds),
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        # Lock exists and is still held by someone else.
        return None
    return token if doc and doc.get("token") == token else None


async def release_lease(job_id: str, token: str) -> None:
    await mongo.db.scheduler_locks.update_one(
        {"_id": job_id, "token": token},
        {"$set": {"expires_at": datetime.now(timezone.utc), "released_at": datetime.now(timezone.utc)}},
    )


def singleton_job(job_id: str, *, lease_seconds: float = 30 * 60):
    """
    Decorate an async job so only one process runs it at a time.
    lease_seconds must exceed the job's worst-case runtime.
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T | None]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            if not _locks_enabled():
                return await fn(*args, **kwargs)
            try:
                token = await acquire_lease(job_id, lease_seconds)
            except Exception:
                logger.exception("Scheduler lock unavailable for %s; skipping this run", job_id)
                return None
            if token is None:
                logger.debug("Job %s is running elsewhere; skipping", job_id)
                return None
            try:
                return await fn(*args, **kwargs)
            finally:
                try:
                    await release_lease(job_id, token)
                except Exception:
                    logger.exception("Failed to release scheduler lock %s (it will expire)", job_id)

        wrapper.job_id = job_id
        return wrapper

    return decorator
