"""
Audit logging service.

Responsibilities:
- Record user and system actions
- Capture request metadata safely
- NEVER interrupt application flow

Design rules:
- Must be failure-safe
- Must not raise exceptions
- Must not perform business logic
"""

from datetime import datetime, timezone
from bson import ObjectId
from app.db.mongo import db
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ======================================================
# SAFE HELPERS
# ======================================================

def _safe_getattr(obj: Any, attr: str):
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def _get_client_ip(request: Any) -> str | None:
    """
    Safely extract client IP from a FastAPI/Starlette request.
    Returns None if unavailable.
    """
    if not request:
        return None

    headers = _safe_getattr(request, "headers")
    if isinstance(headers, dict):
        xff = headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()

    client = _safe_getattr(request, "client")
    host = _safe_getattr(client, "host")
    if isinstance(host, str):
        return host

    return None


def _get_user_agent(request: Any) -> str | None:
    headers = _safe_getattr(request, "headers")
    if isinstance(headers, dict):
        return headers.get("user-agent")
    return None


# ======================================================
# MAIN AUDIT ENTRYPOINT
# ======================================================

async def audit_log(
    *,
    action: str,
    request=None,
    user: dict | None = None,
    meta: dict | None = None,
):
    """
    Persist an audit log entry.

    Parameters:
    - action: UPPER_SNAKE_CASE action name
    - request: FastAPI Request (optional)
    - user: dict with keys:
        - user_id (str)
        - username (optional)
        - auth_provider (optional)
    - meta: arbitrary JSON-safe metadata
    """

    try:
        ip = _get_client_ip(request)
        user_agent = _get_user_agent(request)
    except Exception as exc:
        # 🚨 Audit must never crash the app
        logger.warning("Audit request parsing failed: %s", exc)
        ip = None
        user_agent = None

    try:
        await db.audit_logs.insert_one({
            "user_id": (
                ObjectId(user["user_id"])
                if user and user.get("user_id")
                else None
            ),
            "username": user.get("username") if user else None,
            "auth_provider": user.get("auth_provider") if user else None,
            "action": action,
            "ip": ip,
            "user_agent": user_agent,
            "meta": meta or {},
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception as exc:
        # 🚨 Absolute last line of defense
        logger.error("Audit log insert failed: %s", exc)
