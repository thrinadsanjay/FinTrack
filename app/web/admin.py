from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from copy import deepcopy
import secrets
import logging
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from bson import ObjectId

from app.core.guards import admin_required
from app.core.csrf import verify_csrf_token
from app.core.config import settings
from app.db.mongo import db
from app.services.users import list_users
from app.services.audit import audit_log
from app.services.admin_settings import get_admin_settings, save_admin_settings
from app.services.telegram import (
    send_message,
    set_webhook,
    get_webhook_info,
    delete_webhook,
)
from app.services.telegram_polling import run_telegram_poll_once, get_telegram_poll_status
from app.services.web_push import send_push_notification_alert
from app.web.templates import templates

router = APIRouter()
LOGO_UPLOAD_DIR = Path("app/frontend/static/uploads/logos")
logger = logging.getLogger(__name__)


def _to_aware_utc(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_protected_local_admin(user_doc: dict) -> bool:
    return bool(
        user_doc
        and user_doc.get("auth_provider") == "local"
        and user_doc.get("is_admin")
    )


def _audit_actor(request: Request) -> dict:
    session_user = (request.session.get("user") or {}) if request else {}
    return {
        "user_id": str(session_user.get("user_id") or ""),
        "username": session_user.get("username"),
        "auth_provider": session_user.get("auth_provider"),
    }


@router.get("")
@admin_required
async def admin_dashboard(request: Request):
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)

    users = await list_users()
    users_sorted = sorted(
        users,
        key=lambda u: u.get("created_at") or 0,
        reverse=True,
    )

    for user in users_sorted:
        user["_id"] = str(user.get("_id"))

    total_users = len(users_sorted)
    total_admins = sum(1 for u in users_sorted if u.get("is_admin"))
    total_local = sum(1 for u in users_sorted if u.get("auth_provider") == "local")
    total_keycloak = sum(1 for u in users_sorted if u.get("auth_provider") == "keycloak")
    active_users_24h = 0
    active_users_7d = 0
    for u in users_sorted:
        last_login = _to_aware_utc(u.get("last_login_at"))
        if not last_login:
            continue
        if last_login >= since_24h:
            active_users_24h += 1
        if last_login >= since_7d:
            active_users_7d += 1

    total_accounts = await db.accounts.count_documents({"deleted_at": None})
    total_transactions = await db.transactions.count_documents(
        {"deleted_at": None, "is_failed": {"$ne": True}}
    )
    failed_transactions = await db.transactions.count_documents(
        {"deleted_at": None, "is_failed": True}
    )

    volume_pipeline = [
        {"$match": {"deleted_at": None, "is_failed": {"$ne": True}}},
        {"$group": {"_id": None, "total": {"$sum": {"$ifNull": ["$amount", 0]}}}},
    ]
    volume_result = await db.transactions.aggregate(volume_pipeline).to_list(length=1)
    total_volume_processed = float(volume_result[0]["total"]) if volume_result else 0.0

    server_status = "UP"
    db_status = "DOWN"
    try:
        await db.command("ping")
        db_status = "UP"
    except Exception:
        db_status = "DOWN"

    admin_settings = await get_admin_settings()
    telegram_cfg = (admin_settings.get("telegram") or {}).copy()
    if not str(telegram_cfg.get("webhook_url") or "").strip():
        telegram_cfg["webhook_url"] = _default_telegram_webhook_url()
    admin_settings["telegram"] = telegram_cfg

    settings_status = str(request.query_params.get("settings") or "").strip().lower()
    admin_alert_success = None
    admin_alert_error = None
    if settings_status == "updated":
        admin_alert_success = "Settings saved successfully."
    elif settings_status == "maintenance_updated":
        admin_alert_success = "Maintenance settings updated successfully."
    elif settings_status == "failed":
        admin_alert_error = "Unable to save settings. Please retry."

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": request.session.get("user"),
            "current_admin_user_id": (request.session.get("user") or {}).get("user_id"),
            "active_page": "admin",
            "stats": {
                "total_users": total_users,
                "total_admins": total_admins,
                "total_local": total_local,
                "total_keycloak": total_keycloak,
                "total_accounts": total_accounts,
                "total_transactions": total_transactions,
                "active_users_24h": active_users_24h,
                "active_users_7d": active_users_7d,
                "total_volume_processed": total_volume_processed,
                "failed_transactions": failed_transactions,
                "server_status": server_status,
                "db_status": db_status,
            },
            "admin_settings": admin_settings,
            "admin_alert_success": admin_alert_success,
            "admin_alert_error": admin_alert_error,
            "users": users_sorted[:100],
        },
    )


def _bool_from_form(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "on", "yes"}


def _is_email(value: str) -> bool:
    _, addr = parseaddr(value or "")
    return bool(addr and "@" in addr and "." in addr.split("@")[-1])


def _default_telegram_webhook_url() -> str:
    base = str(settings.FT_BASE_URL or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/api/telegram/webhook"


def _send_smtp_test_mail(*, host: str, port: int, username: str, password: str, from_email: str, to_email: str, tls: bool) -> None:
    msg = EmailMessage()
    msg["Subject"] = "FinTracker SMTP Test"
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(
        "This is a test email from FinTracker Admin SMTP settings.\n\n"
        "If you received this message, SMTP configuration is working."
    )

    with smtplib.SMTP(host, port, timeout=20) as client:
        client.ehlo()
        if tls:
            client.starttls()
            client.ehlo()
        if username:
            client.login(username, password)
        client.send_message(msg)


@router.post("/settings")
@admin_required
async def admin_save_settings(
    request: Request,
    csrf_token: str = Form(...),
    settings_section: str | None = Form(None),
    app_name: str = Form(""),
    logo_url: str = Form(""),
    support_email: str = Form(""),
    support_phone: str = Form(""),
    maintenance_mode: str | None = Form(None),
    maintenance_message: str = Form(""),
    debug_mode: str | None = Form(None),
    smtp_enabled: str | None = Form(None),
    smtp_host: str = Form(""),
    smtp_port: str = Form(""),
    smtp_username: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from_email: str = Form(""),
    smtp_tls: str | None = Form(None),
    telegram_enabled: str | None = Form(None),
    telegram_bot_username: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_webhook_url: str = Form(""),
    telegram_polling_enabled: str | None = Form(None),
    push_enabled: str | None = Form(None),
    push_provider: str = Form("webpush"),
    push_vapid_public_key: str = Form(""),
    push_vapid_private_key: str = Form(""),
    push_firebase_api_key: str = Form(""),
    push_firebase_auth_domain: str = Form(""),
    push_firebase_project_id: str = Form(""),
    push_firebase_storage_bucket: str = Form(""),
    push_firebase_messaging_sender_id: str = Form(""),
    push_firebase_app_id: str = Form(""),
    push_firebase_measurement_id: str = Form(""),
    push_firebase_service_account_json: str = Form(""),
    auth_enabled: str | None = Form(None),
    auth_provider: str = Form("keycloak"),
    auth_keycloak_url: str = Form(""),
    auth_realm: str = Form(""),
    auth_client_id: str = Form(""),
    auth_allow_local_login: str | None = Form(None),
    db_enabled: str | None = Form(None),
    db_mongo_uri: str = Form(""),
    db_mongo_db_name: str = Form(""),
    backup_enabled: str | None = Form(None),
    backup_provider: str = Form("filesystem"),
    backup_schedule_cron: str = Form(""),
    backup_retention_days: str = Form(""),
    backup_destination: str = Form(""),
    logo_file: UploadFile | None = File(None),
):
    verify_csrf_token(request, csrf_token)
    current_settings = await get_admin_settings()
    current_application = current_settings.get("application") or {}
    current_smtp = current_settings.get("smtp") or {}
    current_telegram = current_settings.get("telegram") or {}
    current_push = current_settings.get("push_notifications") or {}

    submitted_smtp_password = smtp_password.strip()
    submitted_telegram_token = telegram_bot_token.strip()
    submitted_firebase_service_account_json = push_firebase_service_account_json.strip()

    settings_payload = {
        "application": {
            "enabled": bool(current_application.get("enabled", True)),
            "app_name": app_name.strip(),
            "logo_url": logo_url.strip(),
            "support_email": support_email.strip(),
            "support_phone": support_phone.strip(),
            "maintenance_mode": _bool_from_form(maintenance_mode),
            "maintenance_message": maintenance_message.strip(),
            "debug_mode": _bool_from_form(debug_mode),
        },
        "smtp": {
            "enabled": _bool_from_form(smtp_enabled),
            "host": smtp_host.strip(),
            "port": smtp_port.strip(),
            "username": smtp_username.strip(),
            "password": submitted_smtp_password or str(current_smtp.get("password") or "").strip(),
            "from_email": smtp_from_email.strip(),
            "tls": _bool_from_form(smtp_tls),
        },
        "telegram": {
            "enabled": _bool_from_form(telegram_enabled),
            "bot_username": telegram_bot_username.strip().lstrip("@"),
            "bot_token": submitted_telegram_token or str(current_telegram.get("bot_token") or "").strip(),
            "webhook_url": telegram_webhook_url.strip() or _default_telegram_webhook_url(),
            "webhook_secret": str(current_telegram.get("webhook_secret") or "").strip(),
            "polling_enabled": _bool_from_form(telegram_polling_enabled),
        },
        "push_notifications": {
            "enabled": _bool_from_form(push_enabled),
            "provider": push_provider.strip(),
            "vapid_public_key": push_vapid_public_key.strip(),
            "vapid_private_key": push_vapid_private_key.strip(),
            "firebase_service_account_json": submitted_firebase_service_account_json or str(current_push.get("firebase_service_account_json") or "").strip(),
            "firebase_config": {
                "apiKey": push_firebase_api_key.strip(),
                "authDomain": push_firebase_auth_domain.strip(),
                "projectId": push_firebase_project_id.strip(),
                "storageBucket": push_firebase_storage_bucket.strip(),
                "messagingSenderId": push_firebase_messaging_sender_id.strip(),
                "appId": push_firebase_app_id.strip(),
                "measurementId": push_firebase_measurement_id.strip(),
            },
        },
        "authentication": {
            "enabled": _bool_from_form(auth_enabled),
            "provider": auth_provider.strip(),
            "keycloak_url": auth_keycloak_url.strip(),
            "realm": auth_realm.strip(),
            "client_id": auth_client_id.strip(),
            "allow_local_login": _bool_from_form(auth_allow_local_login),
        },
        "database": {
            "enabled": _bool_from_form(db_enabled),
            "mongo_uri": db_mongo_uri.strip(),
            "mongo_db_name": db_mongo_db_name.strip(),
        },
        "backup": {
            "enabled": _bool_from_form(backup_enabled),
            "provider": backup_provider.strip(),
            "schedule_cron": backup_schedule_cron.strip(),
            "retention_days": backup_retention_days.strip(),
            "destination": backup_destination.strip(),
        },
    }

    section_key_raw = str(settings_section or "").strip().lower()
    section_key_map = {
        "application": "application",
        "smtp": "smtp",
        "telegram": "telegram",
        "push": "push_notifications",
        "push_notifications": "push_notifications",
        "authentication": "authentication",
        "database": "database",
        "backup": "backup",
    }
    selected_section = section_key_map.get(section_key_raw)

    if bool(current_application.get("maintenance_mode")):
        frozen_settings = deepcopy(current_settings)
        frozen_app = (frozen_settings.get("application") or {}).copy()
        frozen_app["maintenance_mode"] = _bool_from_form(maintenance_mode)
        frozen_app["maintenance_message"] = maintenance_message.strip()
        frozen_settings["application"] = frozen_app
        await save_admin_settings(frozen_settings)
        await audit_log(
            action="ADMIN_SETTINGS_MAINTENANCE_UPDATED",
            request=request,
            user=_audit_actor(request),
            meta={
                "maintenance_mode": frozen_app.get("maintenance_mode"),
                "maintenance_message_length": len(str(frozen_app.get("maintenance_message") or "")),
            },
        )
        return RedirectResponse("/admin?settings=maintenance_updated#settings", status_code=303)

    if (selected_section in {None, "application"}) and logo_file and logo_file.filename:
        safe_ext = Path(logo_file.filename).suffix.lower()
        if safe_ext in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
            LOGO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            file_name = f"logo-{uuid4().hex}{safe_ext}"
            target = LOGO_UPLOAD_DIR / file_name
            content = await logo_file.read()
            target.write_bytes(content)
            settings_payload["application"]["logo_url"] = f"/static/uploads/logos/{file_name}"

    if selected_section:
        merged_settings = deepcopy(current_settings)
        merged_settings[selected_section] = settings_payload[selected_section]
        await save_admin_settings(merged_settings)
        await audit_log(
            action="ADMIN_SETTINGS_UPDATED",
            request=request,
            user=_audit_actor(request),
            meta={
                "section": selected_section,
                "section_saved": True,
            },
        )
        return RedirectResponse(f"/admin?settings=updated&section={selected_section}#settings", status_code=303)

    await save_admin_settings(settings_payload)
    await audit_log(
        action="ADMIN_SETTINGS_UPDATED",
        request=request,
        user=_audit_actor(request),
        meta={
            "maintenance_mode": settings_payload["application"].get("maintenance_mode"),
            "debug_mode": settings_payload["application"].get("debug_mode"),
            "smtp_enabled": settings_payload["smtp"].get("enabled"),
            "telegram_enabled": settings_payload["telegram"].get("enabled"),
            "telegram_polling_enabled": settings_payload["telegram"].get("polling_enabled"),
            "push_enabled": settings_payload["push_notifications"].get("enabled"),
            "auth_enabled": settings_payload["authentication"].get("enabled"),
            "db_enabled": settings_payload["database"].get("enabled"),
            "backup_enabled": settings_payload["backup"].get("enabled"),
            "logo_updated": bool(settings_payload["application"].get("logo_url")),
            "section": "all",
        },
    )
    return RedirectResponse("/admin?settings=updated#settings", status_code=303)


@router.post("/settings/smtp/test")
@admin_required
async def admin_test_smtp(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    smtp = (payload or {}).get("smtp") or {}
    to_email = str((payload or {}).get("to_email") or "").strip()

    current_settings = await get_admin_settings()
    current_smtp = (current_settings.get("smtp") or {})

    enabled = bool(smtp.get("enabled"))
    host = str(smtp.get("host") or "").strip()
    port_raw = str(smtp.get("port") or "").strip()
    username = str(smtp.get("username") or "").strip()
    password = str(smtp.get("password") or "").strip() or str(current_smtp.get("password") or "")
    from_email = str(smtp.get("from_email") or "").strip()
    tls = bool(smtp.get("tls"))

    if not enabled:
        await audit_log(action="ADMIN_SMTP_TEST_BLOCKED", request=request, user=_audit_actor(request), meta={"reason": "smtp_disabled"})
        return JSONResponse({"detail": "Enable SMTP first."}, status_code=400)
    if not host:
        return JSONResponse({"detail": "SMTP host is required."}, status_code=400)
    if not port_raw.isdigit():
        return JSONResponse({"detail": "SMTP port must be numeric."}, status_code=400)
    port = int(port_raw)
    if port <= 0 or port > 65535:
        return JSONResponse({"detail": "SMTP port must be between 1 and 65535."}, status_code=400)
    if not from_email or not _is_email(from_email):
        return JSONResponse({"detail": "Valid From Email is required."}, status_code=400)
    if not to_email or not _is_email(to_email):
        return JSONResponse({"detail": "Valid receiver email is required."}, status_code=400)
    if username and not password:
        return JSONResponse({"detail": "SMTP password is required when username is provided."}, status_code=400)

    try:
        _send_smtp_test_mail(
            host=host,
            port=port,
            username=username,
            password=password,
            from_email=from_email,
            to_email=to_email,
            tls=tls,
        )
    except Exception as exc:
        await audit_log(
            action="ADMIN_SMTP_TEST_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"to_email": to_email, "host": host, "port": port, "tls": tls, "error": str(exc)},
        )
        return JSONResponse({"detail": f"SMTP test failed: {exc}"}, status_code=400)

    await audit_log(
        action="ADMIN_SMTP_TEST_SUCCESS",
        request=request,
        user=_audit_actor(request),
        meta={"to_email": to_email, "host": host, "port": port, "tls": tls},
    )
    return JSONResponse({"status": "ok"})


@router.post("/settings/push/test")
@admin_required
async def admin_test_push(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    session_user = request.session.get("user") or {}
    user_id = str(session_user.get("user_id") or "").strip()
    if not ObjectId.is_valid(user_id):
        return JSONResponse({"detail": "Invalid user session."}, status_code=400)

    payload = await request.json()
    title = str((payload or {}).get("title") or "FinTracker Test Notification").strip() or "FinTracker Test Notification"
    message = str((payload or {}).get("message") or "This is a push test from Admin Settings.").strip() or "This is a push test from Admin Settings."

    result = await send_push_notification_alert(
        user_id=ObjectId(user_id),
        key=f"admin_push_test:{uuid4().hex}",
        notif_type="info",
        title=title,
        message=message,
    )

    sent = int(result.get("sent") or 0)
    failed = int(result.get("failed") or 0)
    status = str(result.get("status") or "failed")

    await audit_log(
        action="ADMIN_PUSH_TEST",
        request=request,
        user=_audit_actor(request),
        meta={"status": status, "sent": sent, "failed": failed, "error": result.get("error")},
    )

    if sent <= 0:
        detail = str(result.get("error") or "No active push subscription found for current admin user.")
        return JSONResponse({"detail": f"Push test failed: {detail}", "result": result}, status_code=400)

    return JSONResponse({"status": "ok", "result": result})


@router.post("/settings/telegram/webhook/set")
@admin_required
async def admin_set_telegram_webhook(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    telegram = (payload or {}).get("telegram") or {}
    enabled = bool(telegram.get("enabled"))
    bot_token = str(telegram.get("bot_token") or "").strip()
    webhook_url = str(telegram.get("webhook_url") or "").strip()

    if not bot_token:
        current_settings = await get_admin_settings()
        bot_token = str(((current_settings.get("telegram") or {}).get("bot_token") or "")).strip()

    if not enabled:
        return JSONResponse({"detail": "Enable Telegram integration first."}, status_code=400)
    if not bot_token:
        return JSONResponse({"detail": "Telegram bot token is required."}, status_code=400)
    if not webhook_url:
        return JSONResponse({"detail": "Webhook URL is required."}, status_code=400)
    if not webhook_url.lower().startswith("https://"):
        return JSONResponse({"detail": "Webhook URL must be HTTPS."}, status_code=400)

    # Backward-compatible hardening: generate secret once and attach to setWebhook.
    current_settings = await get_admin_settings()
    telegram_current = (current_settings.get("telegram") or {}).copy()
    webhook_secret = str(telegram_current.get("webhook_secret") or "").strip()
    if not webhook_secret:
        webhook_secret = secrets.token_urlsafe(32)
        telegram_current["webhook_secret"] = webhook_secret
        current_settings["telegram"] = telegram_current
        await save_admin_settings(current_settings)

    result = await set_webhook(
        bot_token=bot_token,
        webhook_url=webhook_url,
        secret_token=webhook_secret,
    )
    if not bool((result or {}).get("ok")):
        await audit_log(
            action="ADMIN_TELEGRAM_WEBHOOK_SET_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"webhook_url": webhook_url, "description": (result or {}).get("description")},
        )
        return JSONResponse({"detail": (result or {}).get("description") or "Failed to set webhook."}, status_code=400)
    await audit_log(
        action="ADMIN_TELEGRAM_WEBHOOK_SET",
        request=request,
        user=_audit_actor(request),
        meta={"webhook_url": webhook_url},
    )
    return JSONResponse({"status": "ok", "result": result.get("result", True)})


@router.post("/settings/telegram/webhook/info")
@admin_required
async def admin_get_telegram_webhook_info(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    telegram = (payload or {}).get("telegram") or {}
    bot_token = str(telegram.get("bot_token") or "").strip()
    if not bot_token:
        current_settings = await get_admin_settings()
        bot_token = str(((current_settings.get("telegram") or {}).get("bot_token") or "")).strip()

    if not bot_token:
        return JSONResponse({"detail": "Telegram bot token is required."}, status_code=400)

    result = await get_webhook_info(bot_token=bot_token)
    if not bool((result or {}).get("ok")):
        await audit_log(
            action="ADMIN_TELEGRAM_WEBHOOK_INFO_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"description": (result or {}).get("description")},
        )
        return JSONResponse({"detail": (result or {}).get("description") or "Failed to fetch webhook info."}, status_code=400)
    await audit_log(
        action="ADMIN_TELEGRAM_WEBHOOK_INFO_VIEWED",
        request=request,
        user=_audit_actor(request),
        meta={"has_url": bool(((result or {}).get("result") or {}).get("url"))},
    )
    return JSONResponse({"status": "ok", "webhook": result.get("result") or {}})


@router.post("/settings/telegram/webhook/delete")
@admin_required
async def admin_delete_telegram_webhook(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    telegram = (payload or {}).get("telegram") or {}
    bot_token = str(telegram.get("bot_token") or "").strip()
    if not bot_token:
        current_settings = await get_admin_settings()
        bot_token = str(((current_settings.get("telegram") or {}).get("bot_token") or "")).strip()
    drop_pending = bool((payload or {}).get("drop_pending_updates"))

    if not bot_token:
        return JSONResponse({"detail": "Telegram bot token is required."}, status_code=400)

    result = await delete_webhook(bot_token=bot_token, drop_pending_updates=drop_pending)
    if not bool((result or {}).get("ok")):
        await audit_log(
            action="ADMIN_TELEGRAM_WEBHOOK_DELETE_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"description": (result or {}).get("description"), "drop_pending_updates": drop_pending},
        )
        return JSONResponse({"detail": (result or {}).get("description") or "Failed to delete webhook."}, status_code=400)
    await audit_log(
        action="ADMIN_TELEGRAM_WEBHOOK_DELETED",
        request=request,
        user=_audit_actor(request),
        meta={"drop_pending_updates": drop_pending},
    )
    return JSONResponse({"status": "ok", "result": result.get("result", True)})


@router.post("/settings/telegram/poll/status")
@admin_required
async def admin_telegram_poll_status(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    await audit_log(
        action="ADMIN_TELEGRAM_POLL_STATUS_VIEWED",
        request=request,
        user=_audit_actor(request),
    )
    return JSONResponse({"status": "ok", "poll": get_telegram_poll_status()})


@router.post("/settings/telegram/poll/run-once")
@admin_required
async def admin_telegram_poll_run_once(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    await run_telegram_poll_once()
    await audit_log(
        action="ADMIN_TELEGRAM_POLL_RUN_ONCE",
        request=request,
        user=_audit_actor(request),
    )
    return JSONResponse({"status": "ok", "poll": get_telegram_poll_status()})


@router.post("/settings/telegram/delivery/status")
@admin_required
async def admin_telegram_delivery_status(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))

    query = {
        "channels.telegram": {"$exists": True},
    }

    total = await db.notifications.count_documents(query)
    sent = await db.notifications.count_documents({**query, "channels.telegram.status": "sent"})
    failed = await db.notifications.count_documents({**query, "channels.telegram.status": "failed"})
    cooldown = await db.notifications.count_documents({**query, "channels.telegram.status": "skipped_cooldown"})

    recent_cursor = (
        db.notifications
        .find(
            {**query, "channels.telegram.status": "failed"},
            {
                "_id": 1,
                "user_id": 1,
                "key": 1,
                "type": 1,
                "title": 1,
                "message": 1,
                "updated_at": 1,
                "channels.telegram": 1,
            },
        )
        .sort("updated_at", -1)
        .limit(8)
    )
    recent_failures = []
    async for item in recent_cursor:
        tg = (item.get("channels") or {}).get("telegram") or {}
        recent_failures.append(
            {
                "id": str(item.get("_id")),
                "user_id": str(item.get("user_id") or ""),
                "key": str(item.get("key") or ""),
                "type": str(item.get("type") or ""),
                "title": str(item.get("title") or ""),
                "message": str(item.get("message") or ""),
                "updated_at": item.get("updated_at").isoformat() if item.get("updated_at") else None,
                "telegram_error": str(tg.get("error") or ""),
                "last_attempt_at": tg.get("last_attempt_at").isoformat() if tg.get("last_attempt_at") else None,
                "last_sent_at": tg.get("last_sent_at").isoformat() if tg.get("last_sent_at") else None,
            }
        )

    await audit_log(
        action="ADMIN_TELEGRAM_DELIVERY_STATUS_VIEWED",
        request=request,
        user=_audit_actor(request),
        meta={"total": total, "sent": sent, "failed": failed, "cooldown": cooldown},
    )

    return JSONResponse(
        {
            "status": "ok",
            "delivery": {
                "total": total,
                "sent": sent,
                "failed": failed,
                "cooldown": cooldown,
                "recent_failures": recent_failures,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    )


@router.post("/settings/telegram/broadcast")
@admin_required
async def admin_broadcast_telegram(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    telegram = (payload or {}).get("telegram") or {}
    message = str((payload or {}).get("message") or "").strip()

    enabled = bool(telegram.get("enabled"))
    bot_token = str(telegram.get("bot_token") or "").strip()
    if not bot_token:
        current_settings = await get_admin_settings()
        bot_token = str(((current_settings.get("telegram") or {}).get("bot_token") or "")).strip()

    if not enabled:
        return JSONResponse({"detail": "Enable Telegram integration first."}, status_code=400)
    if not bot_token:
        return JSONResponse({"detail": "Telegram bot token is required."}, status_code=400)
    if not message:
        return JSONResponse({"detail": "Broadcast message is required."}, status_code=400)
    if len(message) > 3000:
        return JSONResponse({"detail": "Message is too long (max 3000 chars)."}, status_code=400)

    cursor = db.users.find(
        {
            "deleted_at": None,
            "telegram_chat_id": {"$exists": True, "$ne": ""},
        },
        {"telegram_chat_id": 1},
    )
    recipients = [u async for u in cursor]
    total = len(recipients)
    sent = 0
    failed = 0

    for recipient in recipients:
        chat_id = str(recipient.get("telegram_chat_id") or "").strip()
        if not chat_id:
            continue
        try:
            await send_message(bot_token=bot_token, chat_id=chat_id, text=message)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.warning("Telegram broadcast failed for chat_id=%s: %s", chat_id, exc)

    await audit_log(
        action="ADMIN_TELEGRAM_BROADCAST_SENT",
        request=request,
        user=_audit_actor(request),
        meta={"total": total, "sent": sent, "failed": failed, "message_length": len(message)},
    )

    return JSONResponse(
        {
            "status": "ok",
            "total": total,
            "sent": sent,
            "failed": failed,
        }
    )


@router.post("/users/{user_id}/toggle-active")
@admin_required
async def admin_toggle_user_active(
    request: Request,
    user_id: str,
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)

    if not ObjectId.is_valid(user_id):
        return RedirectResponse("/admin", status_code=303)

    actor_user_id = (request.session.get("user") or {}).get("user_id")
    target = await db.users.find_one({"_id": ObjectId(user_id), "deleted_at": None})
    if not target:
        return RedirectResponse("/admin", status_code=303)
    if _is_protected_local_admin(target):
        return RedirectResponse("/admin", status_code=303)

    current_active = bool(target.get("is_active", True))
    next_active = not current_active

    # Prevent admins from disabling themselves.
    if not next_active and actor_user_id == user_id:
        return RedirectResponse("/admin", status_code=303)

    # Prevent disabling the last active admin.
    if not next_active and target.get("is_admin"):
        other_admins = await db.users.count_documents(
            {
                "deleted_at": None,
                "is_active": True,
                "is_admin": True,
                "_id": {"$ne": ObjectId(user_id)},
            }
        )
        if other_admins == 0:
            return RedirectResponse("/admin", status_code=303)

    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"is_active": next_active, "updated_at": datetime.now(timezone.utc)}},
    )
    await audit_log(
        action="ADMIN_USER_ACTIVE_TOGGLED",
        request=request,
        user=_audit_actor(request),
        meta={"target_user_id": user_id, "is_active": next_active},
    )
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{user_id}/toggle-admin")
@admin_required
async def admin_toggle_user_admin(
    request: Request,
    user_id: str,
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)

    if not ObjectId.is_valid(user_id):
        return RedirectResponse("/admin", status_code=303)

    actor_user_id = (request.session.get("user") or {}).get("user_id")
    target = await db.users.find_one({"_id": ObjectId(user_id), "deleted_at": None})
    if not target:
        return RedirectResponse("/admin", status_code=303)
    if _is_protected_local_admin(target):
        return RedirectResponse("/admin", status_code=303)

    current_admin = bool(target.get("is_admin", False))
    next_admin = not current_admin

    # Prevent admins from removing their own admin access.
    if not next_admin and actor_user_id == user_id:
        return RedirectResponse("/admin", status_code=303)

    # Prevent removing the last active admin.
    if not next_admin and target.get("is_active", True):
        other_admins = await db.users.count_documents(
            {
                "deleted_at": None,
                "is_active": True,
                "is_admin": True,
                "_id": {"$ne": ObjectId(user_id)},
            }
        )
        if other_admins == 0:
            return RedirectResponse("/admin", status_code=303)

    update_doc = {"is_admin": next_admin, "updated_at": datetime.now(timezone.utc)}
    update_query = {"$set": update_doc}
    if target.get("auth_provider") == "keycloak":
        # Explicitly clear any legacy persistent override.
        update_query["$unset"] = {"admin_override": ""}

    await db.users.update_one({"_id": ObjectId(user_id)}, update_query)
    await audit_log(
        action="ADMIN_USER_ROLE_TOGGLED",
        request=request,
        user=_audit_actor(request),
        meta={"target_user_id": user_id, "is_admin": next_admin},
    )
    return RedirectResponse("/admin", status_code=303)
