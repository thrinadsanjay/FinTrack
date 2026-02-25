from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.db.mongo import db
from app.routers.deps import get_current_user, require_admin_user
from app.services.notifications import upsert_notification

router = APIRouter(tags=["Chat"])

SUPPORT_AGENT_TIMEOUT = timedelta(minutes=2)
SUPPORT_IDLE_WARN_TIMEOUT = timedelta(minutes=5)
SUPPORT_IDLE_CLOSE_TIMEOUT = timedelta(minutes=10)
SUPPORT_OPEN_STATUSES = ["pending_admin", "active"]


class ChatLogPayload(BaseModel):
    sender: Literal["user", "bot", "admin", "system"]
    message: str = Field(min_length=1, max_length=5000)
    channel: Literal["chatbot", "support"] = "chatbot"
    thread_user_id: str | None = None
    guest_name: str | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_aware(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _serialize_chat_log(doc: dict) -> dict:
    doc["_id"] = str(doc.get("_id"))
    ts = doc.get("timestamp")
    if isinstance(ts, datetime):
        doc["timestamp"] = ts.isoformat()
    return doc


def _serialize_session(doc: dict | None) -> dict:
    if not doc:
        return {"status": "none"}
    out = {
        "status": doc.get("status") or "none",
        "ended_by": doc.get("ended_by"),
        "closed_reason": doc.get("closed_reason"),
    }
    for key in ("started_at", "last_user_message_at", "last_admin_message_at", "closed_at", "updated_at"):
        value = doc.get(key)
        out[key] = value.isoformat() if isinstance(value, datetime) else value
    return out


def _resolve_support_thread_user_id(request: Request) -> str | None:
    session_user = request.session.get("user") or {}
    if session_user.get("user_id"):
        return session_user["user_id"]
    support_guest_id = request.session.get("support_guest_id")
    if support_guest_id:
        return f"guest:{support_guest_id}"
    return None


async def _get_latest_session(user_id: str) -> dict | None:
    return await db.support_sessions.find_one(
        {"user_id": user_id},
        sort=[("updated_at", -1)],
    )


async def _insert_system_support_message(user_id: str, message: str, *, resolved: bool = False) -> None:
    await db.chat_logs.insert_one(
        {
            "user_id": user_id,
            "sender": "system",
            "message": message,
            "channel": "support",
            "timestamp": _now_utc(),
            "resolved": resolved,
            "admin_read": False,
            "user_read": False,
        }
    )


async def _close_support_session(
    *,
    user_id: str,
    ended_by: str,
    reason: str,
    system_message: str,
) -> None:
    now = _now_utc()
    await db.support_sessions.update_one(
        {"user_id": user_id, "status": {"$in": SUPPORT_OPEN_STATUSES}},
        {
            "$set": {
                "status": "closed",
                "ended_by": ended_by,
                "closed_reason": reason,
                "closed_at": now,
                "updated_at": now,
            }
        },
    )
    await db.chat_logs.update_many(
        {
            "channel": "support",
            "user_id": user_id,
            "resolved": {"$ne": True},
        },
        {"$set": {"resolved": True, "updated_at": now}},
    )
    await _insert_system_support_message(user_id, system_message, resolved=True)


async def _ensure_active_session_for_user(
    *,
    user_id: str,
    username: str | None,
    email: str | None,
) -> dict:
    now = _now_utc()
    session = await _get_latest_session(user_id)
    if not session or session.get("status") == "closed":
        session = {
            "session_key": uuid4().hex,
            "user_id": user_id,
            "status": "pending_admin",
            "started_at": now,
            "updated_at": now,
            "last_user_message_at": now,
            "last_admin_message_at": None,
            "inactivity_warned_at": None,
            "unavailable_notified_at": None,
            "ended_by": None,
            "closed_reason": None,
            "closed_at": None,
            "username": username,
            "email": email,
        }
        await db.support_sessions.insert_one(session)
        return session

    updates: dict = {
        "updated_at": now,
        "last_user_message_at": now,
    }
    if username:
        updates["username"] = username
    if email:
        updates["email"] = email
    # User responded after warning; reset inactivity warning.
    await db.support_sessions.update_one(
        {"_id": session["_id"]},
        {
            "$set": updates,
            "$unset": {"inactivity_warned_at": ""},
        },
    )
    session.update(updates)
    session["inactivity_warned_at"] = None
    return session


async def _mark_admin_response(*, user_id: str) -> None:
    now = _now_utc()
    await db.support_sessions.update_one(
        {"user_id": user_id, "status": {"$in": SUPPORT_OPEN_STATUSES}},
        {
            "$set": {
                "status": "active",
                "updated_at": now,
                "last_admin_message_at": now,
            }
        },
    )


async def _apply_timeouts(*, user_id: str | None = None) -> None:
    now = _now_utc()
    query: dict = {"status": {"$in": SUPPORT_OPEN_STATUSES}}
    if user_id:
        query["user_id"] = user_id

    sessions = await db.support_sessions.find(query).to_list(length=2000)
    for session in sessions:
        uid = session.get("user_id")
        if not uid:
            continue

        started_at = _to_aware(session.get("started_at")) or now
        last_user_message_at = _to_aware(session.get("last_user_message_at")) or started_at
        last_admin_message_at = _to_aware(session.get("last_admin_message_at"))
        inactivity_warned_at = _to_aware(session.get("inactivity_warned_at"))
        unavailable_notified_at = _to_aware(session.get("unavailable_notified_at"))

        # Agent unavailable note after 2 minutes without any admin response.
        if (
            not last_admin_message_at
            and not unavailable_notified_at
            and now - started_at >= SUPPORT_AGENT_TIMEOUT
        ):
            await _insert_system_support_message(
                uid,
                "Our agents are currently unavailable. We will notify you once we are back.",
                resolved=False,
            )
            await db.support_sessions.update_one(
                {"_id": session["_id"]},
                {"$set": {"unavailable_notified_at": now, "updated_at": now}},
            )
            unavailable_notified_at = now

        # Idle warning after 5 minutes without user response.
        if not inactivity_warned_at and now - last_user_message_at >= SUPPORT_IDLE_WARN_TIMEOUT:
            await _insert_system_support_message(
                uid,
                "Are we still connected? This session ends in 5 min.",
                resolved=False,
            )
            await db.support_sessions.update_one(
                {"_id": session["_id"]},
                {"$set": {"inactivity_warned_at": now, "updated_at": now}},
            )
            inactivity_warned_at = now

        # Auto-close after 10 minutes without user response.
        if now - last_user_message_at >= SUPPORT_IDLE_CLOSE_TIMEOUT:
            await _close_support_session(
                user_id=uid,
                ended_by="system",
                reason="idle_timeout",
                system_message="Session closed due to inactivity.",
            )


@router.post("/log")
async def log_chat(
    payload: ChatLogPayload,
    request: Request,
):
    message = payload.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message is required",
        )

    session_user = request.session.get("user") or {}
    now = _now_utc()
    log_doc = {
        "sender": payload.sender,
        "message": message,
        "channel": payload.channel,
        "timestamp": now,
        "resolved": False,
    }

    if payload.channel == "support":
        if payload.sender == "user":
            username = None
            email = None
            if session_user.get("user_id"):
                user_id = session_user.get("user_id")
                username = session_user.get("username")
                email = session_user.get("email")
                log_doc["user_id"] = user_id
                log_doc["username"] = username
                log_doc["email"] = email
            else:
                guest_name = (
                    (payload.guest_name or "").strip()
                    or (request.session.get("support_guest_name") or "").strip()
                )
                if not guest_name:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Name is required for support requests",
                    )
                support_guest_id = request.session.get("support_guest_id")
                if not support_guest_id:
                    support_guest_id = uuid4().hex
                    request.session["support_guest_id"] = support_guest_id
                request.session["support_guest_name"] = guest_name

                user_id = f"guest:{support_guest_id}"
                username = guest_name
                log_doc["user_id"] = user_id
                log_doc["username"] = guest_name
                log_doc["guest_name"] = guest_name

            await _apply_timeouts(user_id=user_id)
            await _ensure_active_session_for_user(
                user_id=user_id,
                username=username,
                email=email,
            )
            log_doc["admin_read"] = False
            log_doc["user_read"] = True

        elif payload.sender == "admin":
            if not session_user.get("is_admin"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin privileges required",
                )
            if not payload.thread_user_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="thread_user_id is required for admin messages",
                )
            user_id = payload.thread_user_id
            await _apply_timeouts(user_id=user_id)
            log_doc["user_id"] = user_id
            log_doc["admin_user_id"] = session_user.get("user_id")
            log_doc["admin_username"] = session_user.get("username")
            log_doc["admin_read"] = True
            log_doc["user_read"] = False
            await _mark_admin_response(user_id=user_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only user/admin senders are supported for support channel",
            )
    else:
        # Keep regular chatbot logs tied to logged-in users when possible.
        if session_user.get("user_id"):
            log_doc["user_id"] = session_user.get("user_id")

    if payload.channel == "support" and not log_doc.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login required for support requests",
        )

    result = await db.chat_logs.insert_one(log_doc)
    return {"status": "logged", "message_id": str(result.inserted_id)}


@router.get("/support/threads")
async def list_support_threads(admin=Depends(require_admin_user)):
    _ = admin
    await _apply_timeouts()

    logs = await db.chat_logs.find(
        {"channel": "support", "user_id": {"$exists": True, "$ne": None}}
    ).sort("timestamp", -1).to_list(length=3000)

    if not logs:
        return {"threads": []}

    sessions_cursor = db.support_sessions.find({}, {"user_id": 1, "status": 1, "updated_at": 1})
    sessions = [s async for s in sessions_cursor]
    session_by_user: dict[str, dict] = {}
    for session in sessions:
        uid = session.get("user_id")
        if not uid:
            continue
        current = session_by_user.get(uid)
        current_updated = _to_aware((current or {}).get("updated_at")) if current else None
        candidate_updated = _to_aware(session.get("updated_at"))
        if not current or (candidate_updated and (not current_updated or candidate_updated > current_updated)):
            session_by_user[uid] = session

    latest_by_user: dict[str, dict] = {}
    pending_by_user: dict[str, int] = {}
    user_display_by_user: dict[str, str] = {}
    user_email_by_user: dict[str, str] = {}
    user_ids: list[str] = []

    for log in logs:
        uid = log.get("user_id")
        if not uid:
            continue
        if uid not in latest_by_user:
            latest_by_user[uid] = log
            user_ids.append(uid)
        if log.get("sender") == "user" and not log.get("admin_read"):
            pending_by_user[uid] = pending_by_user.get(uid, 0) + 1
        if not user_display_by_user.get(uid):
            candidate_name = log.get("guest_name") or log.get("username")
            if candidate_name:
                user_display_by_user[uid] = candidate_name
        if not user_email_by_user.get(uid):
            candidate_email = log.get("email")
            if candidate_email:
                user_email_by_user[uid] = candidate_email

    object_ids = [ObjectId(uid) for uid in user_ids if ObjectId.is_valid(uid)]
    users_cursor = db.users.find(
        {"_id": {"$in": object_ids}, "deleted_at": None},
        {"username": 1, "email": 1, "full_name": 1},
    )
    users = {str(u["_id"]): u async for u in users_cursor}

    threads: list[dict] = []
    for uid in user_ids:
        latest = latest_by_user[uid]
        user_doc = users.get(uid, {})
        session = session_by_user.get(uid) or {}
        threads.append(
            {
                "user_id": uid,
                "username": user_doc.get("username")
                or user_display_by_user.get(uid)
                or latest.get("username")
                or "Unknown User",
                "full_name": user_doc.get("full_name"),
                "email": user_doc.get("email") or user_email_by_user.get(uid) or latest.get("email"),
                "last_message": latest.get("message"),
                "last_sender": latest.get("sender"),
                "last_timestamp": latest.get("timestamp").isoformat()
                if isinstance(latest.get("timestamp"), datetime)
                else latest.get("timestamp"),
                "pending_count": pending_by_user.get(uid, 0),
                "session_status": session.get("status") or "none",
            }
        )

    return {"threads": threads}


@router.get("/support/messages/{user_id}")
async def get_support_messages(
    user_id: str,
    admin=Depends(require_admin_user),
):
    _ = admin
    await _apply_timeouts(user_id=user_id)

    logs = await db.chat_logs.find(
        {"channel": "support", "user_id": user_id}
    ).sort("timestamp", 1).to_list(length=800)

    await db.chat_logs.update_many(
        {"channel": "support", "user_id": user_id, "sender": "user", "admin_read": {"$ne": True}},
        {"$set": {"admin_read": True, "admin_read_at": _now_utc()}},
    )

    user_doc = None
    fallback_username = None
    fallback_email = None
    if ObjectId.is_valid(user_id):
        user_doc = await db.users.find_one(
            {"_id": ObjectId(user_id), "deleted_at": None},
            {"username": 1, "email": 1, "full_name": 1},
        )
    for log in reversed(logs):
        if not fallback_username:
            fallback_username = log.get("guest_name") or log.get("username")
        if not fallback_email:
            fallback_email = log.get("email")
        if fallback_username and fallback_email:
            break

    session = await _get_latest_session(user_id)
    return {
        "user": {
            "user_id": user_id,
            "username": (user_doc or {}).get("username") or fallback_username,
            "full_name": (user_doc or {}).get("full_name"),
            "email": (user_doc or {}).get("email") or fallback_email,
        },
        "session": _serialize_session(session),
        "messages": [_serialize_chat_log(log) for log in logs],
    }


@router.post("/support/messages/{user_id}/reply")
async def reply_support_message(
    user_id: str,
    payload: ChatLogPayload,
    admin=Depends(get_current_user),
):
    if not admin.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    if payload.sender != "admin":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="sender must be admin",
        )
    message = payload.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message is required",
        )

    await _apply_timeouts(user_id=user_id)
    now = _now_utc()
    await _mark_admin_response(user_id=user_id)
    result = await db.chat_logs.insert_one(
        {
            "user_id": user_id,
            "sender": "admin",
            "message": message,
            "channel": "support",
            "timestamp": now,
            "admin_user_id": admin.get("user_id"),
            "admin_username": admin.get("username"),
            "resolved": False,
            "admin_read": True,
            "user_read": False,
        }
    )

    if ObjectId.is_valid(user_id):
        try:
            await upsert_notification(
                user_id=ObjectId(user_id),
                key=f"support_reply:{result.inserted_id}",
                notif_type="info",
                title="Support Reply",
                message="Support replied to your chat. Click to open Help & Support.",
                is_read=False,
            )
        except Exception:
            # Notifications are best-effort for support messages.
            pass

    return {"status": "sent"}


@router.post("/support/messages/{user_id}/end")
async def end_support_chat_by_admin(
    user_id: str,
    admin=Depends(get_current_user),
):
    if not admin.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    await _close_support_session(
        user_id=user_id,
        ended_by="admin",
        reason="admin_end",
        system_message="Chat ended by admin.",
    )
    return {"status": "ended"}


@router.get("/support/my/messages")
async def get_my_support_messages(request: Request):
    thread_user_id = _resolve_support_thread_user_id(request)
    if not thread_user_id:
        return {"user_id": None, "session": {"status": "none"}, "messages": []}

    await _apply_timeouts(user_id=thread_user_id)
    logs = await db.chat_logs.find(
        {"channel": "support", "user_id": thread_user_id}
    ).sort("timestamp", 1).to_list(length=800)

    await db.chat_logs.update_many(
        {
            "channel": "support",
            "user_id": thread_user_id,
            "sender": "admin",
            "user_read": {"$ne": True},
        },
        {"$set": {"user_read": True, "user_read_at": _now_utc()}},
    )

    session = await _get_latest_session(thread_user_id)
    return {
        "user_id": thread_user_id,
        "session": _serialize_session(session),
        "messages": [_serialize_chat_log(log) for log in logs],
    }


@router.post("/support/end")
async def end_support_chat(request: Request):
    thread_user_id = _resolve_support_thread_user_id(request)
    if not thread_user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active support chat",
        )

    await _close_support_session(
        user_id=thread_user_id,
        ended_by="user",
        reason="user_end",
        system_message="Chat ended by user.",
    )
    return {"status": "ended"}
