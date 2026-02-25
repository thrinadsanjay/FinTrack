from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from copy import deepcopy
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from bson import ObjectId

from app.core.guards import admin_required
from app.core.csrf import verify_csrf_token
from app.db.mongo import db
from app.services.users import list_users
from app.services.admin_settings import get_admin_settings, save_admin_settings
from app.web.templates import templates

router = APIRouter()
LOGO_UPLOAD_DIR = Path("app/frontend/static/uploads/logos")


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
            "users": users_sorted[:100],
        },
    )


def _bool_from_form(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "on", "yes"}


def _is_email(value: str) -> bool:
    _, addr = parseaddr(value or "")
    return bool(addr and "@" in addr and "." in addr.split("@")[-1])


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
    telegram_chat_id: str = Form(""),
    push_enabled: str | None = Form(None),
    push_provider: str = Form("webpush"),
    push_vapid_public_key: str = Form(""),
    push_vapid_private_key: str = Form(""),
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
            "password": smtp_password.strip(),
            "from_email": smtp_from_email.strip(),
            "tls": _bool_from_form(smtp_tls),
        },
        "telegram": {
            "enabled": _bool_from_form(telegram_enabled),
            "bot_username": telegram_bot_username.strip().lstrip("@"),
            "bot_token": telegram_bot_token.strip(),
            "chat_id": telegram_chat_id.strip(),
        },
        "push_notifications": {
            "enabled": _bool_from_form(push_enabled),
            "provider": push_provider.strip(),
            "vapid_public_key": push_vapid_public_key.strip(),
            "vapid_private_key": push_vapid_private_key.strip(),
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

    if bool(current_application.get("maintenance_mode")):
        frozen_settings = deepcopy(current_settings)
        frozen_app = (frozen_settings.get("application") or {}).copy()
        frozen_app["maintenance_mode"] = _bool_from_form(maintenance_mode)
        frozen_app["maintenance_message"] = maintenance_message.strip()
        frozen_settings["application"] = frozen_app
        await save_admin_settings(frozen_settings)
        return RedirectResponse("/admin#settings", status_code=303)

    if logo_file and logo_file.filename:
        safe_ext = Path(logo_file.filename).suffix.lower()
        if safe_ext in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
            LOGO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            file_name = f"logo-{uuid4().hex}{safe_ext}"
            target = LOGO_UPLOAD_DIR / file_name
            content = await logo_file.read()
            target.write_bytes(content)
            settings_payload["application"]["logo_url"] = f"/static/uploads/logos/{file_name}"

    await save_admin_settings(settings_payload)
    return RedirectResponse("/admin#settings", status_code=303)


@router.post("/settings/smtp/test")
@admin_required
async def admin_test_smtp(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    smtp = (payload or {}).get("smtp") or {}
    to_email = str((payload or {}).get("to_email") or "").strip()

    enabled = bool(smtp.get("enabled"))
    host = str(smtp.get("host") or "").strip()
    port_raw = str(smtp.get("port") or "").strip()
    username = str(smtp.get("username") or "").strip()
    password = str(smtp.get("password") or "")
    from_email = str(smtp.get("from_email") or "").strip()
    tls = bool(smtp.get("tls"))

    if not enabled:
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
        return JSONResponse({"detail": f"SMTP test failed: {exc}"}, status_code=400)

    return JSONResponse({"status": "ok"})


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
    return RedirectResponse("/admin", status_code=303)
