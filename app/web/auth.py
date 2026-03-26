"""
Web auth routes.
Handles UI, forms, sessions, redirects.
Login API:
- local     -> username/password form
- keycloak  -> redirect to Keycloak OAuth2 with callback
- passkey   -> WebAuthn login with platform biometric/PIN
Password reset for local users.

Logout user based on auth provider:
- local     -> clear session and redirect to /login
- keycloak  -> clear session and redirect to Keycloak logout URL
"""

import urllib.parse
import secrets
import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse

from app.core.config import settings
from app.core.csrf import verify_csrf_token
from app.core.http import get_async_http_client
from app.db.mongo import db
from app.services.auth import (
    authenticate_local_user,
    authenticate_oauth_user,
    reset_user_password,
)
from app.services.audit import audit_log
from app.services.admin_settings import get_admin_settings
from app.services.metrics import (
    mark_user_logged_in,
    mark_user_logged_out,
    set_total_users,
)
from app.services.passkeys import (
    build_authentication_options,
    verify_authentication,
)
from app.services.users import count_active_users_total, update_last_login, get_user_by_mobile_any
from app.helpers.phone import normalize_phone_number
from app.web.templates import templates

router = APIRouter()
PASSKEY_LOGIN_SESSION_KEY = "passkey_login_pending"
PASSKEY_REAUTH_SESSION_KEY = "passkey_reauth_pending"
PASSKEY_CHALLENGE_TTL_SECONDS = 5 * 60

TELEGRAM_LOGIN_OTP_TTL_MINUTES = 10
TELEGRAM_LOGIN_PHONE_REGEX = re.compile(r"^\+?[0-9]{8,15}$")
TELEGRAM_LOGIN_OTP_REGEX = re.compile(r"^\d{6}$")


async def _sync_user_metrics_on_login(user_id: str):
    # Keep auth flow resilient: metrics failures must not block login.
    try:
        mark_user_logged_in(user_id)
        set_total_users(await count_active_users_total())
    except Exception:
        pass


async def _sync_user_metrics_on_logout(user_id: str | None):
    try:
        if user_id:
            mark_user_logged_out(user_id)
        set_total_users(await count_active_users_total())
    except Exception:
        pass


def _callback_uri_from_request(request: Request) -> str:
    # Prefer configured public URL so redirects remain correct behind proxies/TLS termination.
    base_url = (settings.FT_BASE_URL or "").strip().rstrip("/")
    if base_url:
        return f"{base_url}/callback"

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}/callback"


def _session_user_payload(user: dict) -> dict:
    auth_provider = str(user.get("auth_provider") or "local")
    payload = {
        "user_id": str(user["_id"]),
        "auth_provider": auth_provider,
        "username": user.get("username") or user.get("full_name") or "user",
        "is_admin": bool(user.get("is_admin", False)),
    }
    if auth_provider == "keycloak":
        payload["full_name"] = user.get("full_name")
        payload["email"] = user.get("email")
    return payload

async def _auth_settings_state() -> dict:
    admin_settings = await get_admin_settings()
    app_cfg = (admin_settings or {}).get("application") or {}
    auth_cfg = (admin_settings or {}).get("authentication") or {}
    telegram_cfg = (admin_settings or {}).get("telegram") or {}

    auth_enabled = bool(auth_cfg.get("enabled", True))
    local_enabled = bool(auth_cfg.get("allow_local_login", True))
    google_enabled = bool(auth_cfg.get("allow_google_login", True))
    telegram_login_enabled = bool(auth_cfg.get("allow_telegram_login", False))
    telegram_enabled = bool(telegram_cfg.get("enabled", False))

    return {
        "auth_enabled": auth_enabled,
        "local_enabled": bool(auth_enabled and local_enabled),
        "oauth_enabled": bool(auth_enabled),
        "google_enabled": bool(auth_enabled and google_enabled),
        "telegram_enabled": bool(auth_enabled and telegram_login_enabled and telegram_enabled),
        "telegram_bot_username": str(telegram_cfg.get("bot_username") or "").strip(),
        "default_telegram_country": str(
            app_cfg.get("default_country")
            or auth_cfg.get("default_telegram_country")
            or "IN"
        ).strip() or "IN",
    }


def _is_register_command(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    command = value.split()[0].lower()
    if "@" in command:
        command = command.split("@", 1)[0]
    return command == "/register"


async def _send_telegram_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with get_async_http_client() as client:
        response = await client.post(url, json={"chat_id": chat_id, "text": text})
        payload: dict = {}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        ok = bool(payload.get("ok"))
        if response.status_code >= 400 or not ok:
            description = str(payload.get("description") or "").strip() or f"HTTP {response.status_code}"
            if "chat not found" in description.lower():
                description = "Chat not found. Open your Telegram bot and send /register first."
            raise RuntimeError(description)


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
        response = await client.get(url, params={"limit": 100, "allowed_updates": '["message"]'})
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
        body = str(message.get("text") or "").strip()
        if _is_register_command(body):
            chat = message.get("chat") or {}
            chat_id = str(chat.get("id") or "").strip()
            if chat_id:
                user_from = message.get("from") or {}
                return {
                    "chat_id": chat_id,
                    "telegram_username": str(user_from.get("username") or "").strip(),
                }
    return None



@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    auth_state = await _auth_settings_state()
    return templates.TemplateResponse("login.html", {"request": request, "auth_state": auth_state})


@router.post("/login/local")
async def local_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    auth_state = await _auth_settings_state()
    if not auth_state.get("local_enabled"):
        msg = urllib.parse.quote_plus("Local login is disabled by admin.")
        return RedirectResponse(f"/login?auth=failed&error=local_disabled&msg={msg}", status_code=303)

    try:
        user = await authenticate_local_user(
            username=username,
            password=password,
            request=request,
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            request.session.clear()
            return RedirectResponse("/help-support?account=disabled", status_code=303)
        raise

    if not user:
        return RedirectResponse("/login?auth=failed&error=invalid", status_code=303)

    request.session["user"] = _session_user_payload(user)
    await _sync_user_metrics_on_login(str(user["_id"]))

    if user.get("must_reset_password"):
        request.session["force_pwd_reset"] = True
        return RedirectResponse("/reset-password", status_code=303)

    return RedirectResponse("/?auth=success", status_code=303)


@router.post("/login/passkey/options")
async def passkey_login_options(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    username = str((payload or {}).get("username") or "").strip()
    pending_user_id = ""
    allow_credential_ids: list[str] = []

    if username:
        user = await db.users.find_one({"username": username, "deleted_at": None, "is_active": True})
        if not user:
            user = await db.users.find_one({"email": username, "deleted_at": None, "is_active": True})

        passkeys = list((user or {}).get("passkeys") or [])
        allow_credential_ids = [
            str(entry.get("credential_id") or "").strip()
            for entry in passkeys
            if str(entry.get("credential_id") or "").strip()
        ]

        if not user or not allow_credential_ids:
            await audit_log(
                action="PASSKEY_LOGIN_OPTIONS_FAILED",
                request=request,
                user={"username": username, "auth_provider": "passkey"},
                meta={"reason": "user_or_passkey_not_found"},
            )
            return JSONResponse({"detail": "Passkey login is not configured for this account."}, status_code=400)

        if not bool(user.get("biometric_enabled", True)):
            await audit_log(
                action="PASSKEY_LOGIN_OPTIONS_FAILED",
                request=request,
                user={"username": username, "auth_provider": "passkey"},
                meta={"reason": "biometric_disabled"},
            )
            return JSONResponse({"detail": "Biometric login is disabled for this account."}, status_code=403)

        pending_user_id = str(user.get("_id") or "")

    options = build_authentication_options(
        request=request,
        allow_credential_ids=allow_credential_ids,
    )
    request.session[PASSKEY_LOGIN_SESSION_KEY] = {
        "challenge": str(options.get("challenge") or ""),
        "user_id": pending_user_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=PASSKEY_CHALLENGE_TTL_SECONDS)).isoformat(),
    }

    return JSONResponse({"status": "ok", "options": options})


@router.post("/login/passkey/verify")
async def passkey_login_verify(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    pending = request.session.get(PASSKEY_LOGIN_SESSION_KEY) or {}
    if not pending:
        return JSONResponse({"detail": "Passkey challenge not found. Try again."}, status_code=400)

    expires_raw = str(pending.get("expires_at") or "").strip()
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                request.session.pop(PASSKEY_LOGIN_SESSION_KEY, None)
                return JSONResponse({"detail": "Passkey challenge expired. Try again."}, status_code=400)
        except Exception:
            request.session.pop(PASSKEY_LOGIN_SESSION_KEY, None)
            return JSONResponse({"detail": "Invalid passkey challenge state. Try again."}, status_code=400)

    payload = await request.json()
    credential = (payload or {}).get("credential") or {}
    credential_id = str((credential or {}).get("id") or "").strip()
    if not credential_id:
        return JSONResponse({"detail": "Passkey credential is required."}, status_code=400)

    user_id = str(pending.get("user_id") or "").strip()
    user = None
    if user_id and ObjectId.is_valid(user_id):
        user = await db.users.find_one({"_id": ObjectId(user_id), "deleted_at": None, "is_active": True})

    if not user:
        user = await db.users.find_one({"passkeys.credential_id": credential_id, "deleted_at": None, "is_active": True})
        if user:
            user_id = str(user.get("_id") or "")

    if not user:
        request.session.pop(PASSKEY_LOGIN_SESSION_KEY, None)
        return JSONResponse({"detail": "User not found or inactive."}, status_code=400)

    if not bool(user.get("biometric_enabled", True)):
        request.session.pop(PASSKEY_LOGIN_SESSION_KEY, None)
        return JSONResponse({"detail": "Biometric login is disabled for this account."}, status_code=403)

    matched = None
    for entry in list(user.get("passkeys") or []):
        if str(entry.get("credential_id") or "") == credential_id:
            matched = entry
            break

    if not matched:
        await audit_log(
            action="PASSKEY_LOGIN_VERIFY_FAILED",
            request=request,
            user={"user_id": user_id, "auth_provider": "passkey"},
            meta={"reason": "credential_not_registered"},
        )
        return JSONResponse({"detail": "This passkey is not registered for your account."}, status_code=400)

    challenge = str(pending.get("challenge") or "").strip()
    try:
        new_sign_count = verify_authentication(
            request=request,
            credential=credential,
            expected_challenge_b64url=challenge,
            credential_public_key_b64url=str(matched.get("public_key") or ""),
            credential_sign_count=int(matched.get("sign_count") or 0),
        )
    except Exception as exc:
        await audit_log(
            action="PASSKEY_LOGIN_VERIFY_FAILED",
            request=request,
            user={"user_id": user_id, "auth_provider": "passkey"},
            meta={"reason": "verification_error", "error": str(exc)},
        )
        return JSONResponse({"detail": f"Passkey verification failed: {exc}"}, status_code=400)

    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"_id": ObjectId(user_id), "passkeys.credential_id": credential_id},
        {
            "$set": {
                "passkeys.$.sign_count": int(new_sign_count),
                "passkeys.$.last_used_at": now,
                "updated_at": now,
            }
        },
    )
    await update_last_login(user_id)

    request.session["user"] = _session_user_payload(user)
    request.session.pop(PASSKEY_LOGIN_SESSION_KEY, None)

    await audit_log(
        action="PASSKEY_LOGIN_SUCCESS",
        request=request,
        user={
            "user_id": str(user.get("_id")),
            "username": user.get("username"),
            "auth_provider": user.get("auth_provider") or "local",
        },
        meta={"credential_id": credential_id},
    )
    await _sync_user_metrics_on_login(str(user.get("_id")))

    if user.get("must_reset_password"):
        request.session["force_pwd_reset"] = True

    return JSONResponse({"status": "ok", "redirect": "/"})


@router.get("/auth/passkey/unlock/status")
async def passkey_unlock_status(request: Request):
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"status": "ok", "unlock_required": False, "authenticated": False})

    user = await db.users.find_one({"_id": ObjectId(user_id), "deleted_at": None, "is_active": True})
    if not user:
        return JSONResponse({"status": "ok", "unlock_required": False, "authenticated": False})

    passkeys = [
        str(entry.get("credential_id") or "").strip()
        for entry in list(user.get("passkeys") or [])
        if str(entry.get("credential_id") or "").strip()
    ]
    biometric_enabled = bool(user.get("biometric_enabled", True))
    unlock_required = bool(biometric_enabled and len(passkeys) > 0)

    return JSONResponse(
        {
            "status": "ok",
            "authenticated": True,
            "user_id": str(user.get("_id")),
            "biometric_enabled": biometric_enabled,
            "passkey_count": len(passkeys),
            "unlock_required": unlock_required,
        }
    )


@router.post("/auth/passkey/unlock/options")
async def passkey_unlock_options(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not user_id or not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    user = await db.users.find_one({"_id": ObjectId(user_id), "deleted_at": None, "is_active": True})
    if not user:
        return JSONResponse({"detail": "User not found or inactive."}, status_code=400)

    if not bool(user.get("biometric_enabled", True)):
        return JSONResponse({"detail": "Biometric login is disabled for this account."}, status_code=403)

    allow_credential_ids = [
        str(entry.get("credential_id") or "").strip()
        for entry in list(user.get("passkeys") or [])
        if str(entry.get("credential_id") or "").strip()
    ]
    if not allow_credential_ids:
        return JSONResponse({"detail": "No biometric credentials registered."}, status_code=400)

    options = build_authentication_options(
        request=request,
        allow_credential_ids=allow_credential_ids,
    )
    request.session[PASSKEY_REAUTH_SESSION_KEY] = {
        "challenge": str(options.get("challenge") or ""),
        "user_id": user_id,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=PASSKEY_CHALLENGE_TTL_SECONDS)).isoformat(),
    }

    return JSONResponse({"status": "ok", "options": options})


@router.post("/auth/passkey/unlock/verify")
async def passkey_unlock_verify(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    session_user_id = str(session_user.get("user_id") or "").strip()
    if not session_user_id or not ObjectId.is_valid(session_user_id):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    pending = request.session.get(PASSKEY_REAUTH_SESSION_KEY) or {}
    if not pending:
        return JSONResponse({"detail": "Biometric challenge not found. Try again."}, status_code=400)

    pending_user_id = str(pending.get("user_id") or "").strip()
    if not pending_user_id or pending_user_id != session_user_id:
        request.session.pop(PASSKEY_REAUTH_SESSION_KEY, None)
        return JSONResponse({"detail": "Invalid biometric challenge state."}, status_code=400)

    expires_raw = str(pending.get("expires_at") or "").strip()
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(expires_raw)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                request.session.pop(PASSKEY_REAUTH_SESSION_KEY, None)
                return JSONResponse({"detail": "Biometric challenge expired. Try again."}, status_code=400)
        except Exception:
            request.session.pop(PASSKEY_REAUTH_SESSION_KEY, None)
            return JSONResponse({"detail": "Invalid biometric challenge state."}, status_code=400)

    payload = await request.json()
    credential = (payload or {}).get("credential") or {}
    credential_id = str((credential or {}).get("id") or "").strip()
    if not credential_id:
        return JSONResponse({"detail": "Passkey credential is required."}, status_code=400)

    user = await db.users.find_one({"_id": ObjectId(session_user_id), "deleted_at": None, "is_active": True})
    if not user:
        request.session.pop(PASSKEY_REAUTH_SESSION_KEY, None)
        return JSONResponse({"detail": "User not found or inactive."}, status_code=400)

    if not bool(user.get("biometric_enabled", True)):
        request.session.pop(PASSKEY_REAUTH_SESSION_KEY, None)
        return JSONResponse({"detail": "Biometric login is disabled for this account."}, status_code=403)

    matched = None
    for entry in list(user.get("passkeys") or []):
        if str(entry.get("credential_id") or "") == credential_id:
            matched = entry
            break

    if not matched:
        request.session.pop(PASSKEY_REAUTH_SESSION_KEY, None)
        return JSONResponse({"detail": "This passkey is not registered for your account."}, status_code=400)

    challenge = str(pending.get("challenge") or "").strip()
    try:
        new_sign_count = verify_authentication(
            request=request,
            credential=credential,
            expected_challenge_b64url=challenge,
            credential_public_key_b64url=str(matched.get("public_key") or ""),
            credential_sign_count=int(matched.get("sign_count") or 0),
        )
    except Exception as exc:
        return JSONResponse({"detail": f"Biometric verification failed: {exc}"}, status_code=400)

    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"_id": ObjectId(session_user_id), "passkeys.credential_id": credential_id},
        {
            "$set": {
                "passkeys.$.sign_count": int(new_sign_count),
                "passkeys.$.last_used_at": now,
                "updated_at": now,
            }
        },
    )

    request.session.pop(PASSKEY_REAUTH_SESSION_KEY, None)
    request.session["biometric_unlocked_at"] = now.isoformat()

    await audit_log(
        action="PASSKEY_APP_UNLOCK_SUCCESS",
        request=request,
        user=session_user,
        meta={"credential_id": credential_id},
    )

    return JSONResponse({"status": "ok"})


@router.get("/login/oauth")
async def login_oauth(request: Request, idp: str | None = None):
    auth_state = await _auth_settings_state()
    if not auth_state.get("oauth_enabled"):
        msg = urllib.parse.quote_plus("OAuth login is disabled by admin.")
        return RedirectResponse(f"/login?auth=failed&error=oauth_disabled&msg={msg}", status_code=303)

    provider_hint = str(idp or "").strip().lower()
    if provider_hint == "google" and not auth_state.get("google_enabled"):
        msg = urllib.parse.quote_plus("Google login is disabled by admin.")
        return RedirectResponse(f"/login?auth=failed&error=google_disabled&msg={msg}", status_code=303)

    oauth_state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = oauth_state
    callback_uri = _callback_uri_from_request(request)
    request.session["oauth_callback_uri"] = callback_uri

    params = {
        "client_id": settings.FT_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": callback_uri,
        "state": oauth_state,
    }
    provider_hint = str(idp or "").strip().lower()
    if provider_hint in {"google"}:
        params["kc_idp_hint"] = provider_hint

    url = (
        f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}"
        "/protocol/openid-connect/auth?"
        + urllib.parse.urlencode(params)
    )

    return RedirectResponse(url)


@router.post("/login/telegram/send-otp")
async def login_telegram_send_otp(
    request: Request,
    mobile: str = Form(""),
    country_code: str = Form(""),
    mobile_local: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    auth_state = await _auth_settings_state()
    if not auth_state.get("telegram_enabled"):
        msg = urllib.parse.quote_plus("Telegram login is disabled by admin.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_disabled&msg={msg}", status_code=303)

    auth_state = await _auth_settings_state()
    phone = normalize_phone_number(
        mobile=mobile,
        country_code=country_code,
        local_number=mobile_local,
        default_country_iso=auth_state.get("default_telegram_country") or "IN",
    )
    if not TELEGRAM_LOGIN_PHONE_REGEX.match(phone):
        msg = urllib.parse.quote_plus("Enter a valid mobile number.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_mobile&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    admin_settings = await get_admin_settings()
    telegram_cfg = (admin_settings or {}).get("telegram") or {}
    if not telegram_cfg.get("enabled"):
        msg = urllib.parse.quote_plus("Telegram login is disabled by admin.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_disabled&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    bot_token = str(telegram_cfg.get("bot_token") or "").strip()
    bot_username = str(telegram_cfg.get("bot_username") or "").strip()
    if not bot_token or not bot_username:
        msg = urllib.parse.quote_plus("Telegram bot is not configured.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_config&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    now = datetime.now(timezone.utc)
    user = await get_user_by_mobile_any(phone)
    if not user or not str(user.get("telegram_chat_id") or "").strip():
        msg = urllib.parse.quote_plus("Number not registered.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_no_user&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    chat_id = str(user.get("telegram_chat_id") or "").strip()
    telegram_username = str(user.get("telegram_username") or "").strip()
    otp = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = now + timedelta(minutes=TELEGRAM_LOGIN_OTP_TTL_MINUTES)

    text_body = (
        f"FinTracker login OTP: {otp}\n"
        f"Mobile: {phone}\n"
        f"This OTP expires in {TELEGRAM_LOGIN_OTP_TTL_MINUTES} minutes."
    )
    try:
        await _send_telegram_message(bot_token, chat_id, text_body)
    except Exception as exc:
        msg = urllib.parse.quote_plus(f"Failed to send OTP to Telegram: {str(exc)}")
        return RedirectResponse(f"/login?auth=failed&error=telegram_send&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    await db.telegram_login_verifications.update_one(
        {"mobile": phone},
        {
            "$set": {
                "mobile": phone,
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

    return RedirectResponse(
        f"/login?auth=telegram_otp_sent&mobile={urllib.parse.quote_plus(phone)}",
        status_code=303,
    )


@router.post("/login/telegram/verify-otp")
async def login_telegram_verify_otp(
    request: Request,
    mobile: str = Form(""),
    country_code: str = Form(""),
    mobile_local: str = Form(""),
    otp: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    auth_state = await _auth_settings_state()
    if not auth_state.get("telegram_enabled"):
        msg = urllib.parse.quote_plus("Telegram login is disabled by admin.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_disabled&msg={msg}", status_code=303)

    auth_state = await _auth_settings_state()
    phone = normalize_phone_number(
        mobile=mobile,
        country_code=country_code,
        local_number=mobile_local,
        default_country_iso=auth_state.get("default_telegram_country") or "IN",
    )
    code = str(otp or "").strip()

    if not TELEGRAM_LOGIN_PHONE_REGEX.match(phone):
        msg = urllib.parse.quote_plus("Enter a valid mobile number.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_mobile&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)
    if not TELEGRAM_LOGIN_OTP_REGEX.match(code):
        msg = urllib.parse.quote_plus("OTP must be a 6-digit code.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_otp&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    pending = await db.telegram_login_verifications.find_one({"mobile": phone})
    if not pending:
        msg = urllib.parse.quote_plus("No OTP request found. Please send OTP first.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_otp_missing&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    now = datetime.now(timezone.utc)
    expires_at = pending.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except Exception:
            expires_at = None
    if isinstance(expires_at, datetime) and expires_at < now:
        await db.telegram_login_verifications.delete_one({"_id": pending["_id"]})
        msg = urllib.parse.quote_plus("OTP expired. Please request a new OTP.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_otp_expired&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    if str(pending.get("otp") or "") != code:
        await db.telegram_login_verifications.update_one(
            {"_id": pending["_id"]},
            {"$inc": {"attempts": 1}, "$set": {"updated_at": now}},
        )
        msg = urllib.parse.quote_plus("Invalid OTP.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_otp_invalid&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    user = await get_user_by_mobile_any(phone)
    if not user:
        msg = urllib.parse.quote_plus("No account found for this number. Link Telegram from profile first.")
        return RedirectResponse(f"/login?auth=failed&error=telegram_no_user&mobile={urllib.parse.quote_plus(phone)}&msg={msg}", status_code=303)

    if user.get("deleted_at") is not None or not user.get("is_active", True):
        request.session.clear()
        return RedirectResponse("/help-support?account=disabled", status_code=303)

    request.session["user"] = _session_user_payload(user)
    await update_last_login(str(user.get("_id")))
    await _sync_user_metrics_on_login(str(user.get("_id")))

    await audit_log(
        action="TELEGRAM_LOGIN_SUCCESS",
        request=request,
        user={
            "user_id": str(user.get("_id")),
            "username": user.get("username") or user.get("full_name"),
            "auth_provider": user.get("auth_provider") or "local",
        },
        meta={
            "mobile": phone,
            "telegram_username": str(pending.get("telegram_username") or ""),
        },
    )

    await db.telegram_login_verifications.delete_one({"_id": pending["_id"]})
    return RedirectResponse("/?auth=success", status_code=303)


@router.get("/callback")
async def callback(request: Request, code: str, state: str | None = None):
    auth_state = await _auth_settings_state()
    if not auth_state.get("oauth_enabled"):
        msg = urllib.parse.quote_plus("OAuth login is disabled by admin.")
        return RedirectResponse(f"/login?auth=failed&error=oauth_disabled&msg={msg}", status_code=303)

    expected_state = request.session.get("oauth_state")
    if not expected_state or not state or state != expected_state:
        return RedirectResponse("/login?auth=failed&error=oauth_state", status_code=303)
    request.session.pop("oauth_state", None)

    token_url = (
        f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}/"
        "protocol/openid-connect/token"
    )
    callback_uri = request.session.pop("oauth_callback_uri", None) or _callback_uri_from_request(request)

    async with get_async_http_client() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": settings.FT_CLIENT_ID,
                "code": code,
                "redirect_uri": callback_uri,
            },
        )
        resp.raise_for_status()
        token = resp.json()
        id_token = token.get("id_token")
        if not id_token:
            return RedirectResponse("/login?auth=failed&error=oauth_token", status_code=303)

    try:
        user = await authenticate_oauth_user(
            id_token=id_token,
            request=request,
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            request.session.clear()
            return RedirectResponse("/help-support?account=disabled", status_code=303)
        raise

    request.session["user"] = _session_user_payload(user)
    await _sync_user_metrics_on_login(str(user["_id"]))

    return RedirectResponse("/?auth=success", status_code=303)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    if not request.session.get("force_pwd_reset"):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "reset_password.html",
        {"request": request},
    )


@router.get("/account-disabled", response_class=HTMLResponse)
async def account_disabled_page(request: Request):
    request.session.clear()
    return RedirectResponse("/help-support?account=disabled", status_code=303)


@router.post("/reset-password")
async def reset_password_submit(
    request: Request,
    password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    if not request.session.get("force_pwd_reset"):
        return RedirectResponse("/", status_code=303)

    if password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "error": "Passwords do not match"},
        )

    user = request.session["user"]
    await reset_user_password(
        user=user,
        password=password,
        request=request,
    )

    request.session.pop("force_pwd_reset", None)
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    user = request.session.get("user")
    user_id = (user or {}).get("user_id")
    auth_provider = user.get("auth_provider") if user else None

    # ---- Audit logout BEFORE clearing session ----
    await audit_log(
        action="LOGOUT",
        request=request,
        user=user,
        meta={
            "logout_type": "keycloak" if auth_provider == "keycloak" else "local",
        },
    )

    # ---- Clear session ----
    request.session.clear()
    await _sync_user_metrics_on_logout(user_id)

    # ---- Redirect logic ----
    if auth_provider == "keycloak":
        logout_url = (
            f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}"
            "/protocol/openid-connect/logout"
            f"?client_id={settings.FT_CLIENT_ID}"
            f"&post_logout_redirect_uri={settings.FT_BASE_URL}/login"
        )
        return RedirectResponse(logout_url, status_code=302)

    return RedirectResponse("/login", status_code=302)
