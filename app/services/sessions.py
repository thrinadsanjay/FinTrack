"""Server-side auth session records for Security Center.

Starlette cookies remain the session transport. This collection lets a user
see active logins and revoke other cookies via session_epoch.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import Request

from app.db.mongo import db

logger = logging.getLogger(__name__)

_EPOCH_CACHE: dict[str, tuple[int, float]] = {}
_REVOKED_SIDS: set[str] = set()
_CACHE_TTL = 20.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ip(request: Request | None) -> str | None:
    if not request:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:80]
    client = request.client
    return (client.host if client else None)


def invalidate_session_cache(user_id: str | None = None, sid: str | None = None) -> None:
    if user_id:
        _EPOCH_CACHE.pop(str(user_id), None)
    if sid:
        _REVOKED_SIDS.add(sid)


async def _cached_epoch(user_id: str) -> int:
    now = time.monotonic()
    cached = _EPOCH_CACHE.get(user_id)
    if cached and cached[1] > now:
        return cached[0]
    doc = await db.users.find_one({"_id": ObjectId(user_id)}, {"session_epoch": 1})
    epoch = int((doc or {}).get("session_epoch") or 0)
    _EPOCH_CACHE[user_id] = (epoch, now + _CACHE_TTL)
    return epoch


async def record_login_session(request: Request, user_id: str, *, method: str) -> None:
    sid = secrets.token_urlsafe(24)
    epoch = await _cached_epoch(str(user_id))
    request.session["sid"] = sid
    request.session["epoch"] = epoch
    ua = str(request.headers.get("user-agent") or "")[:300]
    try:
        await db.auth_sessions.insert_one(
            {
                "user_id": ObjectId(user_id),
                "sid": sid,
                "method": method,
                "ip": _ip(request),
                "user_agent": ua,
                "created_at": _now(),
                "last_seen_at": _now(),
                "revoked_at": None,
            }
        )
    except Exception:
        logger.exception("Failed to record auth session")


async def touch_session(request: Request) -> None:
    sid = request.session.get("sid")
    if not sid:
        return
    try:
        await db.auth_sessions.update_one(
            {"sid": sid, "revoked_at": None},
            {"$set": {"last_seen_at": _now()}},
        )
    except Exception:
        logger.exception("Failed to touch auth session")


async def is_request_session_valid(request: Request) -> bool:
    user = request.session.get("user") or {}
    user_id = str(user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return False
    db_epoch = await _cached_epoch(user_id)
    cookie_epoch = request.session.get("epoch")
    if cookie_epoch is None:
        return db_epoch == 0
    try:
        if int(cookie_epoch) != db_epoch:
            return False
    except (TypeError, ValueError):
        return False
    sid = request.session.get("sid")
    if not sid:
        return True
    if sid in _REVOKED_SIDS:
        return False
    rec = await db.auth_sessions.find_one({"sid": sid}, {"revoked_at": 1, "user_id": 1})
    if rec is None:
        return True
    if rec.get("revoked_at"):
        _REVOKED_SIDS.add(sid)
        return False
    if str(rec.get("user_id")) != user_id:
        return False
    return True


async def list_sessions(user_id: str, current_sid: str | None = None) -> list[dict]:
    rows = []
    cursor = db.auth_sessions.find({"user_id": ObjectId(user_id), "revoked_at": None}).sort("last_seen_at", -1).limit(20)
    async for doc in cursor:
        rows.append(
            {
                "id": str(doc["_id"]),
                "sid": doc.get("sid"),
                "method": doc.get("method") or "session",
                "ip": doc.get("ip"),
                "user_agent": doc.get("user_agent") or "",
                "created_at": doc.get("created_at"),
                "last_seen_at": doc.get("last_seen_at"),
                "current": bool(current_sid and doc.get("sid") == current_sid),
            }
        )
    return rows


async def is_sid_revoked(sid: str | None) -> bool:
    """True if this cookie's server-side session was individually signed out."""
    if not sid:
        return False
    if sid in _REVOKED_SIDS:
        return True
    rec = await db.auth_sessions.find_one({"sid": sid}, {"revoked_at": 1})
    if rec and rec.get("revoked_at"):
        _REVOKED_SIDS.add(sid)
        return True
    return False


async def revoke_session(user_id: str, session_id: str, *, current_sid: str | None) -> bool:
    """
    Sign out one of the user's other sessions. The current session is refused
    (use Logout for that). Returns False if the session isn't found/active.
    """
    if not ObjectId.is_valid(session_id):
        return False
    rec = await db.auth_sessions.find_one(
        {"_id": ObjectId(session_id), "user_id": ObjectId(user_id), "revoked_at": None},
        {"sid": 1},
    )
    if not rec:
        return False
    if current_sid and rec.get("sid") == current_sid:
        raise ValueError("You can't sign out the session you're using. Use Logout instead.")
    result = await db.auth_sessions.update_one(
        {"_id": rec["_id"], "revoked_at": None},
        {"$set": {"revoked_at": _now()}},
    )
    invalidate_session_cache(sid=rec.get("sid"))
    return result.modified_count == 1


async def revoke_other_sessions(request: Request, user_id: str) -> int:
    current_sid = request.session.get("sid")
    now = _now()
    filt = {"user_id": ObjectId(user_id), "revoked_at": None}
    if current_sid:
        filt["sid"] = {"$ne": current_sid}
    result = await db.auth_sessions.update_many(filt, {"$set": {"revoked_at": now}})
    await db.users.update_one({"_id": ObjectId(user_id)}, {"$inc": {"session_epoch": 1}, "$set": {"updated_at": now}})
    new_user = await db.users.find_one({"_id": ObjectId(user_id)}, {"session_epoch": 1})
    new_epoch = int((new_user or {}).get("session_epoch") or 0)
    request.session["epoch"] = new_epoch
    invalidate_session_cache(user_id)
    _EPOCH_CACHE[str(user_id)] = (new_epoch, time.monotonic() + _CACHE_TTL)
    return int(result.modified_count)


async def revoke_current_session(request: Request) -> None:
    sid = request.session.get("sid")
    user = request.session.get("user") or {}
    user_id = user.get("user_id")
    if sid:
        await db.auth_sessions.update_one({"sid": sid}, {"$set": {"revoked_at": _now()}})
        invalidate_session_cache(str(user_id or ""), sid)
