from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from datetime import datetime, timezone
from datetime import timedelta
import re
import secrets
from urllib.parse import quote_plus
from bson import ObjectId
from app.core.config import settings
from app.core.csrf import verify_csrf_token
from app.core.guards import login_required
from app.core.http import get_async_http_client
from app.db.mongo import db
from app.services.auth import change_local_password
from app.services.audit import audit_log
from app.services.dashboard import get_user_notifications
from app.services.users import get_user_by_id
from app.services.admin_settings import get_admin_settings
from app.helpers.phone import normalize_phone_number
from app.services.passkeys import build_registration_options, verify_registration
from app.web.templates import templates

router = APIRouter()
OTP_TTL_MINUTES = 10
OTP_REGEX = re.compile(r"^\d{6}$")
PHONE_REGEX = re.compile(r"^\+?[0-9]{8,15}$")
PASSKEY_REGISTER_SESSION_KEY = "passkey_register_pending"
PASSKEY_CHALLENGE_TTL_SECONDS = 5 * 60


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

    reset_error = str(request.query_params.get("reset_error") or "").strip()
    reset_updated = str(request.query_params.get("updated") or "").strip() == "1"
    reset_modal_open = (
        str(request.query_params.get("reset") or "").strip() == "1"
        or reset_updated
        or bool(reset_error)
    )

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
        "passkey_count": len(list((db_user or {}).get("passkeys") or [])),
        "biometric_enabled": bool((db_user or {}).get("biometric_enabled", True)),
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
        request=request,
        name="profile.html",
        context={
            "request": request,
            "user": session_user,
            "profile": profile,
            "notifications": notifications,
            "active_page": "profile",
            "reset_password_modal_open": reset_modal_open,
            "reset_password_error": reset_error,
            "reset_password_updated": reset_updated,
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

    return RedirectResponse("/profile?reset=1", status_code=303)


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

    if new_password != confirm_password:
        msg = quote_plus("New password and confirm password do not match.")
        return RedirectResponse(f"/profile?reset=1&reset_error={msg}", status_code=303)

    if len(new_password) < 8:
        msg = quote_plus("Password must be at least 8 characters.")
        return RedirectResponse(f"/profile?reset=1&reset_error={msg}", status_code=303)

    try:
        await change_local_password(
            user_id=session_user["user_id"],
            current_password=current_password,
            new_password=new_password,
            request=request,
        )
    except Exception as exc:
        msg = quote_plus(str(getattr(exc, "detail", str(exc)) or "Failed to update password."))
        return RedirectResponse(f"/profile?reset=1&reset_error={msg}", status_code=303)

    return RedirectResponse("/profile?reset=1&updated=1", status_code=303)

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
                    "Chat not found. Open your Telegram bot and send /register first."
                )
            raise RuntimeError(description)


def _is_register_command(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    command = value.split()[0].lower()
    if "@" in command:
        command = command.split("@", 1)[0]
    return command == "/register"


async def _resolve_chat_id_from_register(bot_token: str, since: datetime | None = None) -> dict | None:
    if since:
        intent = await db.telegram_register_intents.find_one(
            {
                "created_at": {"$gte": since},
                "$or": [
                    {"used_by_user_id": {"$exists": False}},
                    {"used_by_user_id": ""},
                    {"used_by_user_id": None},
                ],
            },
            sort=[("created_at", -1)],
        )
        if intent:
            return {
                "chat_id": str(intent.get("chat_id") or "").strip(),
                "telegram_username": str(intent.get("telegram_username") or "").strip(),
            }

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
        msg_unix = (message or {}).get("date")
        if since and isinstance(msg_unix, int):
            msg_time = datetime.fromtimestamp(msg_unix, tz=timezone.utc)
            if msg_time < since:
                continue
        text = str(message.get("text") or "").strip()
        if _is_register_command(text):
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
    admin_settings = await get_admin_settings()
    app_cfg = (admin_settings or {}).get("application") or {}
    auth_cfg = (admin_settings or {}).get("authentication") or {}
    mobile = normalize_phone_number(
        mobile=(payload or {}).get("mobile"),
        country_iso=(payload or {}).get("country_iso"),
        country_code=(payload or {}).get("country_code"),
        local_number=(payload or {}).get("mobile_local"),
        default_country_iso=app_cfg.get("default_country") or auth_cfg.get("default_telegram_country") or "IN",
    )
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
    register_requested_at = _to_aware_utc((pending or {}).get("register_requested_at")) or (now - timedelta(minutes=15))
    bot_url = f"https://t.me/{bot_username}"

    chat_info = None
    try:
        chat_info = await _resolve_chat_id_from_register(bot_token, register_requested_at)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    if not chat_info:
        await db.telegram_otp_verifications.update_one(
            {"user_id": user_oid},
            {
                "$set": {
                    "user_id": user_oid,
                    "mobile": mobile,
                    "register_requested_at": now,
                    "bot_username": bot_username,
                    "status": "awaiting_register",
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return JSONResponse(
            {
                "status": "awaiting_register",
                "bot_url": bot_url,
                "detail": "Send /register in Telegram bot, then click Send OTP to receive OTP.",
            },
            status_code=202,
        )

    otp = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = now + timedelta(minutes=OTP_TTL_MINUTES)
    chat_id = str(chat_info.get("chat_id") or "").strip()
    telegram_username = str(chat_info.get("telegram_username") or "").strip()
    await db.telegram_register_intents.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "used_by_user_id": str(user_oid),
                "used_at": now,
            }
        },
    )

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
            "bot_url": bot_url,
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
    admin_settings = await get_admin_settings()
    telegram_cfg = (admin_settings or {}).get("telegram") or {}
    bot_token = str(telegram_cfg.get("bot_token") or "").strip()
    if bot_token and chat_id:
        display_name = str(session_user.get("username") or "there").strip() or "there"
        welcome_text = (
            f"Welcome {display_name}! Telegram is now linked to your FinTracker account.\n"
            "You will now receive updates and alerts here."
        )
        try:
            await _send_telegram_message(bot_token, chat_id, welcome_text)
        except Exception:
            pass
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


@router.post("/profile/passkeys/register/options")
@login_required


async def profile_passkey_register_options(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    db_user = await get_user_by_id(user_id)
    if not db_user:
        return JSONResponse({"detail": "User not found."}, status_code=404)
    if not bool(db_user.get("biometric_enabled", True)):
        return JSONResponse({"detail": "Biometric login is disabled in your profile settings."}, status_code=403)

    username = str((db_user.get("username") or session_user.get("username") or db_user.get("email") or "")).strip()
    if not username:
        return JSONResponse({"detail": "User profile is missing username."}, status_code=400)

    display_name = str((db_user.get("full_name") or db_user.get("username") or username)).strip()
    exclude_ids = [
        str(item.get("credential_id") or "").strip()
        for item in list(db_user.get("passkeys") or [])
        if str(item.get("credential_id") or "").strip()
    ]

    options = build_registration_options(
        request=request,
        user_id=user_id,
        username=username,
        display_name=display_name,
        exclude_credential_ids=exclude_ids,
    )

    request.session[PASSKEY_REGISTER_SESSION_KEY] = {
        "challenge": str(options.get("challenge") or ""),
        "user_id": user_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=PASSKEY_CHALLENGE_TTL_SECONDS)).isoformat(),
    }

    await audit_log(
        action="PASSKEY_REGISTER_OPTIONS_ISSUED",
        request=request,
        user=session_user,
        meta={"exclude_count": len(exclude_ids)},
    )

    return JSONResponse({"status": "ok", "options": options})


@router.post("/profile/passkeys/register/verify")
@login_required


async def profile_passkey_register_verify(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    pending = request.session.get(PASSKEY_REGISTER_SESSION_KEY) or {}
    challenge = str(pending.get("challenge") or "").strip()
    pending_user_id = str(pending.get("user_id") or "").strip()
    if not challenge or not pending_user_id or pending_user_id != user_id:
        return JSONResponse({"detail": "Passkey registration challenge not found. Try again."}, status_code=400)

    db_user = await get_user_by_id(user_id)
    if not db_user:
        request.session.pop(PASSKEY_REGISTER_SESSION_KEY, None)
        return JSONResponse({"detail": "User not found."}, status_code=404)
    if not bool(db_user.get("biometric_enabled", True)):
        request.session.pop(PASSKEY_REGISTER_SESSION_KEY, None)
        return JSONResponse({"detail": "Biometric login is disabled in your profile settings."}, status_code=403)

    expires_raw = str(pending.get("expires_at") or "").strip()
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                request.session.pop(PASSKEY_REGISTER_SESSION_KEY, None)
                return JSONResponse({"detail": "Passkey challenge expired. Please retry."}, status_code=400)
        except Exception:
            request.session.pop(PASSKEY_REGISTER_SESSION_KEY, None)
            return JSONResponse({"detail": "Invalid passkey challenge state. Please retry."}, status_code=400)

    payload = await request.json()
    credential = (payload or {}).get("credential") or {}
    credential_id = str((credential or {}).get("id") or "").strip()
    if not credential_id:
        return JSONResponse({"detail": "Passkey credential is required."}, status_code=400)

    label = str((payload or {}).get("name") or "").strip()

    try:
        verified = verify_registration(
            request=request,
            credential=credential,
            expected_challenge_b64url=challenge,
        )
    except Exception as exc:
        await audit_log(
            action="PASSKEY_REGISTER_VERIFY_FAILED",
            request=request,
            user=session_user,
            meta={"error": str(exc)},
        )
        return JSONResponse({"detail": f"Passkey registration failed: {exc}"}, status_code=400)

    now = datetime.now(timezone.utc)
    credential_id = str(verified.get("credential_id") or credential_id)
    passkey_doc = {
        "credential_id": credential_id,
        "public_key": str(verified.get("public_key") or ""),
        "sign_count": int(verified.get("sign_count") or 0),
        "name": label or "Mobile Passkey",
        "transports": list(((credential.get("response") or {}).get("transports") or [])),
        "created_at": now,
        "last_used_at": now,
    }

    user_oid = ObjectId(user_id)
    await db.users.update_one({"_id": user_oid}, {"$pull": {"passkeys": {"credential_id": credential_id}}})
    await db.users.update_one(
        {"_id": user_oid, "deleted_at": None},
        {"$push": {"passkeys": passkey_doc}, "$set": {"updated_at": now}},
    )

    request.session.pop(PASSKEY_REGISTER_SESSION_KEY, None)

    updated_user = await db.users.find_one({"_id": user_oid}, {"passkeys": 1})
    count = len(list((updated_user or {}).get("passkeys") or []))

    await audit_log(
        action="PASSKEY_REGISTER_SUCCESS",
        request=request,
        user=session_user,
        meta={"credential_id": credential_id, "passkey_count": count},
    )

    return JSONResponse({"status": "ok", "passkey_count": count})


@router.post("/profile/passkeys/delete")
@login_required


async def profile_passkey_delete(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    payload = await request.json()
    credential_id = str((payload or {}).get("credential_id") or "").strip()
    if not credential_id:
        return JSONResponse({"detail": "credential_id is required."}, status_code=400)

    now = datetime.now(timezone.utc)
    user_oid = ObjectId(user_id)
    await db.users.update_one(
        {"_id": user_oid, "deleted_at": None},
        {"$pull": {"passkeys": {"credential_id": credential_id}}, "$set": {"updated_at": now}},
    )

    updated_user = await db.users.find_one({"_id": user_oid}, {"passkeys": 1})
    count = len(list((updated_user or {}).get("passkeys") or []))

    await audit_log(
        action="PASSKEY_DELETED",
        request=request,
        user=session_user,
        meta={"credential_id": credential_id, "passkey_count": count},
    )

    return JSONResponse({"status": "ok", "passkey_count": count})


@router.post("/profile/passkeys/enable")
@login_required
async def profile_passkey_enable(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    now = datetime.now(timezone.utc)
    user_oid = ObjectId(user_id)
    await db.users.update_one(
        {"_id": user_oid, "deleted_at": None},
        {"$set": {"biometric_enabled": True, "updated_at": now}},
    )
    updated_user = await db.users.find_one({"_id": user_oid}, {"passkeys": 1, "biometric_enabled": 1})
    count = len(list((updated_user or {}).get("passkeys") or []))
    biometric_enabled = bool((updated_user or {}).get("biometric_enabled", True))

    await audit_log(
        action="PASSKEY_BIOMETRIC_ENABLED",
        request=request,
        user=session_user,
        meta={"passkey_count": count},
    )
    return JSONResponse({"status": "ok", "biometric_enabled": biometric_enabled, "passkey_count": count})


@router.post("/profile/passkeys/disable")
@login_required
async def profile_passkey_disable(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    now = datetime.now(timezone.utc)
    user_oid = ObjectId(user_id)
    await db.users.update_one(
        {"_id": user_oid, "deleted_at": None},
        {"$set": {"biometric_enabled": False, "updated_at": now}},
    )
    updated_user = await db.users.find_one({"_id": user_oid}, {"passkeys": 1, "biometric_enabled": 1})
    count = len(list((updated_user or {}).get("passkeys") or []))
    biometric_enabled = bool((updated_user or {}).get("biometric_enabled", True))

    request.session.pop(PASSKEY_REGISTER_SESSION_KEY, None)

    await audit_log(
        action="PASSKEY_BIOMETRIC_DISABLED",
        request=request,
        user=session_user,
        meta={"passkey_count": count},
    )
    return JSONResponse({"status": "ok", "biometric_enabled": biometric_enabled, "passkey_count": count})


@router.post("/profile/passkeys/delete-all")
@login_required
async def profile_passkey_delete_all(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=401)

    now = datetime.now(timezone.utc)
    user_oid = ObjectId(user_id)
    await db.users.update_one(
        {"_id": user_oid, "deleted_at": None},
        {"$set": {"passkeys": [], "updated_at": now}},
    )
    updated_user = await db.users.find_one({"_id": user_oid}, {"passkeys": 1, "biometric_enabled": 1})
    count = len(list((updated_user or {}).get("passkeys") or []))
    biometric_enabled = bool((updated_user or {}).get("biometric_enabled", True))

    request.session.pop(PASSKEY_REGISTER_SESSION_KEY, None)

    await audit_log(
        action="PASSKEY_ALL_DELETED",
        request=request,
        user=session_user,
        meta={"passkey_count": count},
    )
    return JSONResponse({"status": "ok", "biometric_enabled": biometric_enabled, "passkey_count": count})


@router.post("/profile/account/disable")
@login_required
async def disable_own_account(request: Request):
    form = await request.form()
    verify_csrf_token(request, form.get("csrf_token"))

    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return RedirectResponse("/login", status_code=303)

    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        {"$set": {"is_active": False, "updated_at": now}},
    )
    await audit_log(
        action="USER_SELF_DISABLED",
        request=request,
        user=session_user,
        meta={"user_id": user_id},
    )
    request.session.clear()
    return RedirectResponse("/help-support?account=disabled", status_code=303)


@router.post("/profile/account/delete")
@login_required
async def soft_delete_own_account(request: Request):
    form = await request.form()
    verify_csrf_token(request, form.get("csrf_token"))

    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return RedirectResponse("/login", status_code=303)

    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"_id": ObjectId(user_id), "deleted_at": None},
        {"$set": {"deleted_at": now, "is_active": False, "updated_at": now}},
    )
    await audit_log(
        action="USER_SELF_DELETED_SOFT",
        request=request,
        user=session_user,
        meta={"user_id": user_id},
    )
    request.session.clear()
    return RedirectResponse("/help-support?account=deleted", status_code=303)
