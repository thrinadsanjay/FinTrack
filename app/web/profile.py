from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from datetime import datetime, timezone
from datetime import timedelta
import re
import secrets
from bson import ObjectId
from app.core.config import settings
from app.core.csrf import verify_csrf_token
from app.core.guards import login_required
from app.core.http import get_async_http_client
from app.db.mongo import db
from app.services.auth import change_local_password
from app.services.dashboard import get_user_notifications
from app.services.users import get_user_by_id
from app.services.admin_settings import get_admin_settings
from app.web.templates import templates

router = APIRouter()
OTP_TTL_MINUTES = 10
OTP_REGEX = re.compile(r"^\d{6}$")
PHONE_REGEX = re.compile(r"^\+?[0-9]{8,15}$")


def _profile_identity(db_user: dict | None, session_user: dict) -> dict:
    return {
        "username": (db_user or {}).get("username") or session_user.get("username") or "",
        "full_name": (db_user or {}).get("full_name") or (db_user or {}).get("username") or session_user.get("username") or "",
        "email": (db_user or {}).get("email") or session_user.get("email") or "",
    }


def _external_password_reset_url(db_user: dict | None) -> str:
    configured_url = (settings.FT_EXTERNAL_PASSWORD_RESET_URL or "").strip()
    if configured_url:
        return configured_url

    idp = ((db_user or {}).get("identity_provider") or "").strip().lower()
    if idp in {"google", "google-oidc"}:
        return "https://myaccount.google.com/security"

    return (
        f"{settings.FT_KEYCLOAK_URL.rstrip('/')}/realms/"
        f"{settings.FT_KEYCLOAK_REALM}/account/#/security/signingin"
    )


def _to_aware_utc(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/profile")
@login_required
async def edit_profile_page(request: Request):
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse("/login", status_code=303)

    db_user = await get_user_by_id(session_user["user_id"])
    source = (db_user or {}).get("auth_provider") or session_user.get("auth_provider") or "local"
    is_external = source != "local"
    password_reset_url = "/profile/reset-password"
    if is_external:
        password_reset_url = _external_password_reset_url(db_user)
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    uid = ObjectId(session_user["user_id"])

    accounts_count = await db.accounts.count_documents({"user_id": uid, "deleted_at": None})
    tx_this_month = await db.transactions.count_documents(
        {
            "user_id": uid,
            "deleted_at": None,
            "created_at": {"$gte": month_start},
            "is_failed": {"$ne": True},
        }
    )
    recurring_active = await db.recurring_deposits.count_documents(
        {
            "user_id": uid,
            "is_active": True,
            "$or": [{"end_date": None}, {"end_date": {"$gte": now}}],
            "ended_at": None,
        }
    )
    unread_count = await db.notifications.count_documents({"user_id": uid, "is_read": False})

    identity = _profile_identity(db_user, session_user)
    profile = {
        "user_id": session_user.get("user_id"),
        "username": identity["username"],
        "full_name": identity["full_name"],
        "email": identity["email"],
        "phone": (db_user or {}).get("phone") or "",
        "auth_provider": source,
        "auth_source_label": "External user" if is_external else "Local user",
        "external_id": (db_user or {}).get("oauth_sub") or (db_user or {}).get("keycloak_id") or "",
        "is_external": is_external,
        "identity_provider": (db_user or {}).get("identity_provider") or "",
        "password_reset_url": password_reset_url,
        "is_admin": bool((db_user or {}).get("is_admin") or session_user.get("is_admin")),
        "is_active": bool((db_user or {}).get("is_active", True)),
        "member_since": (db_user or {}).get("created_at"),
        "last_login_at": (db_user or {}).get("last_login_at"),
        "password_updated_at": (db_user or {}).get("updated_at"),
        "timezone": request.session.get("timezone", "Asia/Kolkata"),
        "theme": request.session.get("theme", "auto"),
        "notifications_enabled": True,
        "telegram_chat_id": (db_user or {}).get("telegram_chat_id") or "",
        "telegram_mobile": (db_user or {}).get("telegram_mobile") or "",
        "telegram_username": (db_user or {}).get("telegram_username") or "",
        "telegram_verified_at": (db_user or {}).get("telegram_verified_at"),
        "stats": {
            "accounts_count": accounts_count,
            "tx_this_month": tx_this_month,
            "recurring_active": recurring_active,
            "unread_notifications": unread_count,
        },
    }

    admin_settings = await get_admin_settings()
    telegram_cfg = (admin_settings or {}).get("telegram") or {}
    profile["telegram_enabled"] = bool(telegram_cfg.get("enabled"))
    profile["telegram_bot_username"] = str(telegram_cfg.get("bot_username") or "").strip()

    notifications = await get_user_notifications(session_user["user_id"])

    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": session_user,
            "profile": profile,
            "notifications": notifications,
            "active_page": "profile",
        }
    )


@router.get("/profile/reset-password")
@login_required
async def reset_password_page(request: Request):
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse("/login", status_code=303)

    db_user = await get_user_by_id(session_user["user_id"])
    if not db_user or db_user.get("auth_provider") != "local":
        return RedirectResponse(_external_password_reset_url(db_user), status_code=303)

    notifications = await get_user_notifications(session_user["user_id"])
    identity = _profile_identity(db_user, session_user)
    return templates.TemplateResponse(
        "profile_reset_password.html",
        {
            "request": request,
            "user": session_user,
            "profile": identity,
            "notifications": notifications,
            "active_page": "profile",
        },
    )


@router.post("/profile/reset-password")
@login_required
async def reset_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    session_user = request.session.get("user")
    if not session_user:
        return RedirectResponse("/login", status_code=303)

    db_user = await get_user_by_id(session_user["user_id"])
    if not db_user or db_user.get("auth_provider") != "local":
        return RedirectResponse("/profile", status_code=303)

    notifications = await get_user_notifications(session_user["user_id"])
    identity = _profile_identity(db_user, session_user)

    if new_password != confirm_password:
        return templates.TemplateResponse(
            "profile_reset_password.html",
            {
                "request": request,
                "user": session_user,
                "profile": identity,
                "notifications": notifications,
                "active_page": "profile",
                "error": "New password and confirm password do not match.",
            },
            status_code=400,
        )
    if len(new_password) < 8:
        return templates.TemplateResponse(
            "profile_reset_password.html",
            {
                "request": request,
                "user": session_user,
                "profile": identity,
                "notifications": notifications,
                "active_page": "profile",
                "error": "Password must be at least 8 characters.",
            },
            status_code=400,
        )

    try:
        await change_local_password(
            user_id=session_user["user_id"],
            current_password=current_password,
            new_password=new_password,
            request=request,
        )
    except Exception as exc:
        msg = getattr(exc, "detail", str(exc))
        return templates.TemplateResponse(
            "profile_reset_password.html",
            {
                "request": request,
                "user": session_user,
                "profile": identity,
                "notifications": notifications,
                "active_page": "profile",
                "error": msg,
            },
            status_code=400,
        )

    return RedirectResponse("/profile/reset-password?updated=1", status_code=303)


async def _send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with get_async_http_client() as client:
        response = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
            },
        )
        payload: dict = {}
        try:
            payload = response.json()
        except Exception:
            payload = {}

        ok = bool(payload.get("ok"))
        if response.status_code >= 400 or not ok:
            description = str(payload.get("description") or "").strip()
            if not description:
                description = f"HTTP {response.status_code}"
            if "chat not found" in description.lower():
                description = (
                    "Chat not found. Open your Telegram bot and press Start first, "
                    "then use your numeric chat id."
                )
            raise RuntimeError(description)


async def _resolve_chat_id_from_start_token(bot_token: str, start_token: str) -> dict | None:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    async with get_async_http_client() as client:
        response = await client.get(
            url,
            params={"limit": 100, "allowed_updates": '["message"]'},
        )
        payload: dict = {}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if response.status_code >= 400 or not payload.get("ok"):
            description = str(payload.get("description") or "").strip() or f"HTTP {response.status_code}"
            raise RuntimeError(f"Unable to read Telegram updates: {description}")

    for update in payload.get("result") or []:
        message = (update or {}).get("message") or {}
        text = str(message.get("text") or "").strip()
        if text == f"/start {start_token}" or text.startswith(f"/start {start_token}"):
            chat = message.get("chat") or {}
            chat_id = str(chat.get("id") or "").strip()
            if chat_id:
                user_from = message.get("from") or {}
                telegram_username = str(user_from.get("username") or "").strip()
                return {
                    "chat_id": chat_id,
                    "telegram_username": telegram_username,
                }
    return None


@router.post("/profile/telegram/send-otp")
@login_required
async def send_telegram_otp(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = session_user.get("user_id")
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    payload = await request.json()
    mobile = str((payload or {}).get("mobile") or "").strip()
    if not PHONE_REGEX.match(mobile):
        return JSONResponse({"detail": "Enter a valid mobile number."}, status_code=400)

    admin_settings = await get_admin_settings()
    telegram_cfg = (admin_settings or {}).get("telegram") or {}
    if not telegram_cfg.get("enabled"):
        return JSONResponse({"detail": "Telegram integration is disabled by admin."}, status_code=400)
    bot_token = str(telegram_cfg.get("bot_token") or "").strip()
    bot_username = str(telegram_cfg.get("bot_username") or "").strip()
    if not bot_token:
        return JSONResponse({"detail": "Telegram bot token is not configured."}, status_code=400)
    if not bot_username:
        return JSONResponse({"detail": "Telegram bot username is not configured by admin."}, status_code=400)

    now = datetime.now(timezone.utc)
    user_oid = ObjectId(user_id)
    pending = await db.telegram_otp_verifications.find_one({"user_id": user_oid})
    start_token = str((pending or {}).get("start_token") or "")
    if not start_token:
        start_token = f"ftreg_{secrets.token_urlsafe(10)}"
    start_url = f"https://t.me/{bot_username}?start={start_token}"

    chat_info = None
    try:
        chat_info = await _resolve_chat_id_from_start_token(bot_token, start_token)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    if not chat_info:
        await db.telegram_otp_verifications.update_one(
            {"user_id": user_oid},
            {
                "$set": {
                    "user_id": user_oid,
                    "mobile": mobile,
                    "start_token": start_token,
                    "bot_username": bot_username,
                    "status": "awaiting_start",
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return JSONResponse(
            {
                "status": "awaiting_start",
                "start_url": start_url,
                "detail": "Open Telegram and press Start on the bot, then click Send OTP again.",
            },
            status_code=202,
        )

    otp = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = now + timedelta(minutes=OTP_TTL_MINUTES)
    chat_id = str(chat_info.get("chat_id") or "").strip()
    telegram_username = str(chat_info.get("telegram_username") or "").strip()

    text = (
        f"FinTracker verification OTP: {otp}\n"
        f"Mobile: {mobile}\n"
        f"This OTP expires in {OTP_TTL_MINUTES} minutes."
    )
    try:
        await _send_telegram_message(bot_token, chat_id, text)
    except Exception as exc:
        return JSONResponse({"detail": f"Failed to send OTP to Telegram: {str(exc)}"}, status_code=400)

    await db.telegram_otp_verifications.update_one(
        {"user_id": user_oid},
        {
            "$set": {
                "user_id": user_oid,
                "mobile": mobile,
                "chat_id": chat_id,
                "telegram_username": telegram_username,
                "otp": otp,
                "expires_at": expires_at,
                "attempts": 0,
                "updated_at": now,
                "bot_username": bot_username,
                "start_token": start_token,
                "status": "otp_sent",
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    return JSONResponse(
        {
            "status": "ok",
            "expires_in_minutes": OTP_TTL_MINUTES,
            "start_url": start_url,
        }
    )


@router.post("/profile/telegram/verify-otp")
@login_required
async def verify_telegram_otp(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = session_user.get("user_id")
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    payload = await request.json()
    otp = str((payload or {}).get("otp") or "").strip()
    if not OTP_REGEX.match(otp):
        return JSONResponse({"detail": "OTP must be a 6-digit code."}, status_code=400)

    pending = await db.telegram_otp_verifications.find_one({"user_id": ObjectId(user_id)})
    if not pending:
        return JSONResponse({"detail": "No OTP request found. Please send OTP first."}, status_code=400)

    now = datetime.now(timezone.utc)
    expires_at = _to_aware_utc(pending.get("expires_at"))
    if expires_at and expires_at < now:
        await db.telegram_otp_verifications.delete_one({"_id": pending["_id"]})
        return JSONResponse({"detail": "OTP expired. Please request a new OTP."}, status_code=400)

    if str(pending.get("otp") or "") != otp:
        await db.telegram_otp_verifications.update_one(
            {"_id": pending["_id"]},
            {"$inc": {"attempts": 1}, "$set": {"updated_at": now}},
        )
        return JSONResponse({"detail": "Invalid OTP."}, status_code=400)

    chat_id = str(pending.get("chat_id") or "").strip()
    mobile = str(pending.get("mobile") or "").strip()
    telegram_username = str(pending.get("telegram_username") or "").strip()
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "telegram_chat_id": chat_id,
                "telegram_mobile": mobile,
                "telegram_username": telegram_username,
                "telegram_verified_at": now,
                "updated_at": now,
            }
        },
    )
    await db.telegram_otp_verifications.delete_one({"_id": pending["_id"]})
    return JSONResponse(
        {
            "status": "ok",
            "telegram_chat_id": chat_id,
            "telegram_mobile": mobile,
            "telegram_username": telegram_username,
        }
    )


@router.post("/profile/telegram/deregister")
@login_required
async def deregister_telegram(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = session_user.get("user_id")
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$unset": {
                "telegram_chat_id": "",
                "telegram_mobile": "",
                "telegram_username": "",
                "telegram_verified_at": "",
            },
            "$set": {"updated_at": now},
        },
    )
    await db.telegram_otp_verifications.delete_many({"user_id": ObjectId(user_id)})
    return JSONResponse({"status": "ok"})
