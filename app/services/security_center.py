"""Aggregate security status without exposing secrets."""

from __future__ import annotations

from bson import ObjectId

from app.db.mongo import db
from app.helpers.labels import user_agent_label
from app.services.sessions import list_sessions, touch_session

SECURITY_ACTIONS = (
    "LOGIN_SUCCESS",
    "SESSION_REVOKED",
    "LOGIN_FAILED",
    "OAUTH_LOGIN_SUCCESS",
    "PASSKEY_LOGIN_SUCCESS",
    "PASSKEY_LOGIN_FAILED",
    "PASSKEY_REGISTERED",
    "PASSKEY_DELETED",
    "TELEGRAM_LOGIN_SUCCESS",
    "LOGOUT",
    "PASSWORD_CHANGED",
    "PASSWORD_RESET",
    "TELEGRAM_LINKED",
    "TELEGRAM_UNLINKED",
    "SESSIONS_REVOKED",
)


def _public_ua(value: str | None) -> str:
    return user_agent_label(value)


async def get_security_overview(request, user_id: str) -> dict:
    await touch_session(request)
    uid = ObjectId(user_id)
    user = await db.users.find_one(
        {"_id": uid},
        {
            "auth_provider": 1,
            "password_hash": 1,
            "passkeys": 1,
            "biometric_enabled": 1,
            "email": 1,
            "telegram_chat_id": 1,
            "last_login_at": 1,
            "session_epoch": 1,
            "google_sub": 1,
        },
    )
    user = user or {}
    passkeys = list(user.get("passkeys") or [])
    provider = str(user.get("auth_provider") or "local")
    has_password = bool(user.get("password_hash"))
    telegram_linked = bool(str(user.get("telegram_chat_id") or "").strip())
    google_enabled = provider == "google" or bool(user.get("google_sub") or (user.get("email") and provider == "google"))
    sessions = await list_sessions(user_id, current_sid=request.session.get("sid"))
    events = []
    cursor = (
        db.audit_logs.find({"user_id": uid, "action": {"$in": list(SECURITY_ACTIONS)}})
        .sort("timestamp", -1)
        .limit(25)
    )
    async for row in cursor:
        events.append(
            {
                "action": row.get("action"),
                "timestamp": row.get("timestamp"),
                "meta": _public_meta(row.get("meta") or {}),
            }
        )

    password_status = "Set" if has_password else "Not set"
    if provider == "google" and not has_password:
        password_status = "Google account"
    passkey_status = "Enabled" if passkeys and user.get("biometric_enabled", True) else (
        "Registered, disabled" if passkeys else "Not registered"
    )

    protected = has_password or bool(passkeys) or google_enabled
    return {
        "status": "Account protected" if protected else "Add a sign-in method",
        "protected": protected,
        "password": {
            "status": password_status,
            "has_password": has_password,
            "manage_href": "/profile#password",
        },
        "passkey": {
            "status": passkey_status,
            "count": len(passkeys),
            "enabled": bool(user.get("biometric_enabled", True)) and bool(passkeys),
            "manage_href": "/profile#password",
        },
        "google": {
            "status": "Enabled" if google_enabled else "Not connected",
            "enabled": google_enabled,
        },
        "telegram": {
            "status": "Linked" if telegram_linked else "Not linked",
            "linked": telegram_linked,
            "manage_href": "/profile#telegram",
        },
        "last_login_at": user.get("last_login_at"),
        "sessions": [
            {
                **row,
                "sid": None,
                "user_agent": _public_ua(row.get("user_agent")),
            }
            for row in sessions
        ],
        "session_count": len(sessions),
        "events": events,
    }


def _public_meta(meta: dict) -> dict:
    blocked = {"token", "secret", "password", "credential_id", "otp", "bot_token"}
    clean = {}
    for key, value in meta.items():
        if str(key).lower() in blocked:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
    return clean
