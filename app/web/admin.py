from datetime import date, datetime, timedelta, timezone
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
from urllib.parse import quote_plus
from bson import ObjectId

from app.core.guards import admin_required
from app.core.csrf import verify_csrf_token
from app.core.config import settings
from app.db.mongo import db
from app.services.users import list_users
from app.services.audit import audit_log
from app.services.admin_settings import get_admin_settings, save_admin_settings
from app.services.backups import (
    run_backup,
    get_backup_status,
    list_backup_history,
    list_local_backups,
    restore_backup,
    restore_backup_file,
    delete_backup,
    delete_backup_file,
    verify_local_backup,
    validate_backup_config,
    describe_backup_config,
)
from app.schedulers.backup_scheduler import configure_backup_schedule
from app.schedulers.recurring_scheduler import configure_recurring_schedule
from app.services.telegram import (
    send_message,
    set_webhook,
    get_webhook_info,
    delete_webhook,
)
from app.services.telegram_polling import run_telegram_poll_once, get_telegram_poll_status
from app.services.web_push import send_push_notification_alert
from app.helpers.recurring_schedule import parse_clock_time, parse_timezone_name
from app.helpers.phone import timezone_from_country_iso, normalize_country_iso
from app.web.templates import templates

router = APIRouter()
LOGO_UPLOAD_DIR = Path("app/frontend/static/uploads/logos")
logger = logging.getLogger(__name__)


def _to_aware_utc(dt: datetime | str | None) -> datetime | None:
    if not dt:
        return None
    if isinstance(dt, str):
        raw = dt.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
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

    backup_status = await get_backup_status()
    backup_cfg = (admin_settings.get("backup") or {}).copy()
    try:
        local_backups = await list_local_backups(8, backup_cfg=backup_cfg)
        local_backup_error = ""
    except Exception as exc:
        local_backups = []
        local_backup_error = str(exc)

    for item in local_backups:
        if isinstance(item, dict):
            item["created_at"] = _to_aware_utc(item.get("created_at"))
            item["updated_at"] = _to_aware_utc(item.get("updated_at"))
            item["verified_at"] = _to_aware_utc(item.get("verified_at"))

    app_cfg = (admin_settings.get("application") or {}).copy()
    smtp_cfg = (admin_settings.get("smtp") or {}).copy()
    push_cfg = (admin_settings.get("push_notifications") or {}).copy()
    auth_cfg = (admin_settings.get("authentication") or {}).copy()
    database_cfg = (admin_settings.get("database") or {}).copy()
    backup_last = (backup_status.get("last_run") or {}).copy()
    backup_status_cfg = (backup_status.get("config") or {}).copy()
    backup_last["started_at"] = _to_aware_utc(backup_last.get("started_at"))
    backup_last["completed_at"] = _to_aware_utc(backup_last.get("completed_at"))
    backup_last["last_restored_at"] = _to_aware_utc(backup_last.get("last_restored_at"))
    backup_status_cfg["next_run"] = _to_aware_utc(backup_status_cfg.get("next_run"))

    service_status = [
        {
            "label": "Debug",
            "enabled": bool(app_cfg.get("debug_mode")),
            "detail": "Verbose application logs" if app_cfg.get("debug_mode") else "Standard logging",
        },
        {
            "label": "SMTP",
            "enabled": bool(smtp_cfg.get("enabled")),
            "detail": str(smtp_cfg.get("host") or "No SMTP host configured").strip() or "No SMTP host configured",
        },
        {
            "label": "Telegram Bot",
            "enabled": bool(telegram_cfg.get("enabled")),
            "detail": str(telegram_cfg.get("bot_username") or "No bot username configured").strip() or "No bot username configured",
        },
        {
            "label": "Telegram Polling",
            "enabled": bool(telegram_cfg.get("enabled") and telegram_cfg.get("polling_enabled")),
            "detail": "Fallback polling active" if telegram_cfg.get("polling_enabled") else "Webhook mode only",
        },
        {
            "label": "Push Notifications",
            "enabled": bool(push_cfg.get("enabled")),
            "detail": "firebase",
        },
        {
            "label": "Authentication",
            "enabled": bool(auth_cfg.get("enabled")),
            "detail": str(auth_cfg.get("provider") or "keycloak").strip() or "keycloak",
        },
        {
            "label": "Local Login",
            "enabled": bool(auth_cfg.get("allow_local_login")),
            "detail": "Allowed" if auth_cfg.get("allow_local_login") else "Blocked",
        },
        {
            "label": "Database",
            "enabled": bool(database_cfg.get("enabled")),
            "detail": str(database_cfg.get("mongo_db_name") or db.name or "MongoDB").strip(),
        },
        {
            "label": "Backups",
            "enabled": bool(backup_status_cfg.get("enabled")),
            "detail": str(backup_status_cfg.get("schedule_display") or "Manual only").strip() or "Manual only",
        },
    ]
    enabled_services = sum(1 for item in service_status if item.get("enabled"))
    verified_local_backups = sum(1 for item in local_backups if item.get("verified"))
    total_transactions_with_failures = total_transactions + failed_transactions
    trend_days = 7
    trend_start = datetime.combine(now.date() - timedelta(days=trend_days - 1), datetime.min.time(), tzinfo=timezone.utc)

    async def _aggregate_daily_counts(collection_name: str, *, match: dict, date_field: str, status_field: str | None = None) -> dict[str, int]:
        pipeline = [{"$match": {**match, date_field: {"$gte": trend_start}}}]
        pipeline.extend([
            {
                "$project": {
                    "day": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": f"${date_field}",
                            "timezone": "UTC",
                        }
                    }
                }
            },
            {"$group": {"_id": "$day", "count": {"$sum": 1}}},
        ])
        rows = await getattr(db, collection_name).aggregate(pipeline).to_list(length=trend_days)
        return {str(row.get("_id")): int(row.get("count") or 0) for row in rows}

    login_counts = {}
    for user_doc in users_sorted:
        last_login = _to_aware_utc(user_doc.get("last_login_at"))
        if not last_login or last_login < trend_start:
            continue
        day_key = last_login.astimezone(timezone.utc).strftime("%Y-%m-%d")
        login_counts[day_key] = login_counts.get(day_key, 0) + 1

    failed_transaction_counts = await _aggregate_daily_counts(
        "transactions",
        match={"deleted_at": None, "is_failed": True},
        date_field="created_at",
    )
    completed_backup_counts = await _aggregate_daily_counts(
        "backup_runs",
        match={"status": "completed"},
        date_field="completed_at",
    )

    trend_labels: list[str] = []
    login_series: list[int] = []
    failed_transaction_series: list[int] = []
    backup_series: list[int] = []
    for offset in range(trend_days):
        day = now.date() - timedelta(days=trend_days - 1 - offset)
        day_key = day.isoformat()
        trend_labels.append(day.strftime("%d %b"))
        login_series.append(int(login_counts.get(day_key, 0)))
        failed_transaction_series.append(int(failed_transaction_counts.get(day_key, 0)))
        backup_series.append(int(completed_backup_counts.get(day_key, 0)))

    failed_transaction_rate = (
        round((failed_transactions / total_transactions_with_failures) * 100, 1)
        if total_transactions_with_failures
        else 0.0
    )

    def _activity_sort_key(user_doc: dict):
        return (
            _to_aware_utc(user_doc.get("last_login_at"))
            or _to_aware_utc(user_doc.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )

    recent_users = []
    for user_doc in sorted(users_sorted, key=_activity_sort_key, reverse=True)[:6]:
        recent_users.append(
            {
                "label": str(
                    user_doc.get("username")
                    or user_doc.get("email")
                    or user_doc.get("full_name")
                    or user_doc.get("first_name")
                    or "Unknown user"
                ).strip(),
                "email": str(user_doc.get("email") or "-").strip() or "-",
                "auth_provider": str(user_doc.get("auth_provider") or "local").strip() or "local",
                "is_admin": bool(user_doc.get("is_admin")),
                "enabled": not bool(user_doc.get("disabled") or user_doc.get("is_disabled")),
                "last_login_at": _to_aware_utc(user_doc.get("last_login_at")),
                "created_at": _to_aware_utc(user_doc.get("created_at")),
            }
        )

    alerts = []
    if db_status != "UP":
        alerts.append({"level": "critical", "title": "Database unavailable", "detail": "MongoDB ping failed from the admin process."})
    if bool(app_cfg.get("maintenance_mode")):
        alerts.append({"level": "warning", "title": "Maintenance mode enabled", "detail": "Public application traffic is currently in maintenance mode."})
    if not bool(backup_status_cfg.get("enabled")):
        alerts.append({"level": "warning", "title": "Scheduled backups disabled", "detail": "Backups can only run manually until scheduling is enabled."})
    elif not verified_local_backups:
        alerts.append({"level": "warning", "title": "No verified local backups", "detail": "Backup files exist, but none are currently verified."})
    if failed_transaction_rate >= 5:
        alerts.append({"level": "warning", "title": "High failed transaction rate", "detail": f"{failed_transaction_rate}% of recorded transactions are marked failed."})
    if not bool(smtp_cfg.get("enabled")):
        alerts.append({"level": "info", "title": "SMTP disabled", "detail": "Email delivery and mail-based alerts are currently disabled."})
    if not alerts:
        alerts.append({"level": "ok", "title": "No active issues detected", "detail": "Core services, backups, and runtime checks look stable from the admin overview."})

    audit_rows = await db.audit_logs.find({}, {"action": 1, "timestamp": 1, "username": 1, "auth_provider": 1, "meta": 1}).sort("timestamp", -1).limit(8).to_list(length=8)
    recent_audit = []
    for row in audit_rows:
        meta = row.get("meta") or {}
        meta_summary_parts = []
        for key in ("user_id", "target_user_id", "section", "provider", "destination"):
            value = meta.get(key)
            if value:
                meta_summary_parts.append(f"{key.replace('_', ' ')}: {value}")
        recent_audit.append(
            {
                "action": str(row.get("action") or "UNKNOWN").replace("_", " ").title(),
                "timestamp": _to_aware_utc(row.get("timestamp")),
                "username": str(row.get("username") or "System").strip() or "System",
                "auth_provider": str(row.get("auth_provider") or "system").strip() or "system",
                "meta_summary": " • ".join(meta_summary_parts[:2]),
            }
        )

    overview = {
        "backup": {
            "last_run": backup_last,
            "config": backup_status_cfg,
            "local_count": len(local_backups),
            "verified_local_count": verified_local_backups,
            "local_error": local_backup_error,
            "recent_local_backups": local_backups[:5],
        },
        "services": service_status,
        "alerts": alerts,
        "recent_users": recent_users,
        "recent_audit": recent_audit,
        "activity": {
            "failed_transaction_rate": failed_transaction_rate,
            "recent_signins_24h": active_users_24h,
            "recent_signins_7d": active_users_7d,
        },
        "trends": {
            "labels": trend_labels,
            "login_series": login_series,
            "failed_transaction_series": failed_transaction_series,
            "backup_series": backup_series,
        },
        "service_counts": {
            "enabled": enabled_services,
            "disabled": len(service_status) - enabled_services,
        },
        "configuration": {
            "app_name": str(app_cfg.get("app_name") or settings.FT_APP_NAME),
            "support_email": str(app_cfg.get("support_email") or settings.FT_SUPPORT_EMAIL or "-").strip() or "-",
            "support_phone": str(app_cfg.get("support_phone") or settings.FT_SUPPORT_PHONE or "-").strip() or "-",
            "auth_provider": str(auth_cfg.get("provider") or "keycloak").strip() or "keycloak",
            "push_provider": "firebase",
            "backup_destination": str(backup_status_cfg.get("destination") or "-").strip() or "-",
        },
    }

    settings_status = str(request.query_params.get("settings") or "").strip().lower()
    settings_error_message = str(request.query_params.get("settings_error") or "").strip()
    admin_alert_success = None
    admin_alert_error = settings_error_message or None
    if settings_status == "failed" and not admin_alert_error:
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
            "overview": overview,
            "admin_alert_success": admin_alert_success,
            "admin_alert_error": admin_alert_error,
            "settings_error_section": str(request.query_params.get("section") or "").strip(),
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


def _normalize_backup_payload(values: dict | None) -> dict:
    backup = (values or {}).get("backup") or values or {}
    schedule_time = str(backup.get("schedule_time") or "").strip()
    schedule_cron = str(backup.get("schedule_cron") or "").strip()
    return {
        "enabled": bool(backup.get("enabled")),
        "provider": str(backup.get("provider") or "filesystem").strip(),
        "schedule_time": schedule_time,
        "schedule_cron": schedule_cron,
        "retention_days": str(backup.get("retention_days") or "").strip(),
        "destination": str(backup.get("destination") or "").strip(),
    }


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
    application_default_country: str = Form("IN"),
    scheduler_run_time: str = Form(""),
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
    push_vapid_public_key: str = Form(""),
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
    auth_default_telegram_country: str = Form("IN"),
    auth_allow_local_login: str | None = Form(None),
    auth_allow_google_login: str | None = Form(None),
    auth_allow_telegram_login: str | None = Form(None),
    db_enabled: str | None = Form(None),
    db_mongo_uri: str = Form(""),
    db_mongo_db_name: str = Form(""),
    backup_enabled: str | None = Form(None),
    backup_provider: str = Form("filesystem"),
    backup_schedule_time: str = Form(""),
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
    current_auth = current_settings.get("authentication") or {}

    submitted_smtp_password = smtp_password.strip()
    submitted_telegram_token = telegram_bot_token.strip()
    submitted_firebase_service_account_json = push_firebase_service_account_json.strip()

    default_country = normalize_country_iso(application_default_country or current_application.get("default_country") or current_auth.get("default_telegram_country") or "IN")
    derived_timezone = timezone_from_country_iso(default_country)

    settings_payload = {
        "application": {
            "enabled": bool(current_application.get("enabled", True)),
            "app_name": app_name.strip(),
            "logo_url": logo_url.strip(),
            "support_email": support_email.strip(),
            "support_phone": support_phone.strip(),
            "default_country": default_country,
            "timezone": derived_timezone,
            "scheduler_run_time": scheduler_run_time.strip(),
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
            "provider": "firebase",
            "vapid_public_key": push_vapid_public_key.strip(),
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
            "default_telegram_country": default_country,
            "allow_local_login": _bool_from_form(auth_allow_local_login),
            "allow_google_login": _bool_from_form(auth_allow_google_login),
            "allow_telegram_login": _bool_from_form(auth_allow_telegram_login),
        },
        "database": {
            "enabled": _bool_from_form(db_enabled),
            "mongo_uri": db_mongo_uri.strip(),
            "mongo_db_name": db_mongo_db_name.strip(),
        },
        "backup": {
            "enabled": _bool_from_form(backup_enabled),
            "provider": backup_provider.strip(),
            "schedule_time": backup_schedule_time.strip(),
            "retention_days": backup_retention_days.strip(),
            "destination": backup_destination.strip(),
        },
    }

    section_key_raw = str(settings_section or "").strip().lower()
    section_key_map = {
        "application": "application",
        "runtime": "runtime",
        "smtp": "smtp",
        "telegram": "telegram",
        "push": "push_notifications",
        "push_notifications": "push_notifications",
        "authentication": "authentication",
        "database": "database",
        "backup": "backup",
    }
    selected_section = section_key_map.get(section_key_raw)

    if selected_section in {None, "application"}:
        try:
            parse_timezone_name(settings_payload["application"].get("timezone") or "")
            parse_clock_time(settings_payload["application"].get("scheduler_run_time") or "")
        except ValueError as exc:
            msg = quote_plus(str(exc))
            return RedirectResponse(f"/admin?settings=failed&section=application&settings_error={msg}#settings", status_code=303)

    if selected_section in {None, "backup"}:
        try:
            timezone_name = str(
                settings_payload["application"].get("timezone")
                or (current_application.get("timezone") or "")
            ).strip() or "Asia/Kolkata"
            validate_backup_config(settings_payload["backup"], timezone_name)
        except ValueError as exc:
            await audit_log(
                action="ADMIN_BACKUP_SETTINGS_VALIDATION_FAILED",
                request=request,
                user=_audit_actor(request),
                meta={"error": str(exc), "section": selected_section or "all"},
            )
            msg = quote_plus(str(exc))
            section = selected_section or "backup"
            return RedirectResponse(f"/admin?settings=failed&section={section}&settings_error={msg}#settings", status_code=303)

    if bool(current_application.get("maintenance_mode")):
        frozen_settings = deepcopy(current_settings)
        frozen_app = (frozen_settings.get("application") or {}).copy()
        frozen_app["maintenance_mode"] = _bool_from_form(maintenance_mode)
        frozen_app["maintenance_message"] = maintenance_message.strip()
        frozen_app["debug_mode"] = _bool_from_form(debug_mode)
        frozen_settings["application"] = frozen_app
        await save_admin_settings(frozen_settings)
        await audit_log(
            action="ADMIN_SETTINGS_MAINTENANCE_UPDATED",
            request=request,
            user=_audit_actor(request),
            meta={
                "maintenance_mode": frozen_app.get("maintenance_mode"),
                "debug_mode": frozen_app.get("debug_mode"),
                "maintenance_message_length": len(str(frozen_app.get("maintenance_message") or "")),
            },
        )
        section_redirect = "runtime" if selected_section == "runtime" else "application"
        return RedirectResponse(f"/admin?settings=maintenance_updated&section={section_redirect}#settings", status_code=303)

    if (selected_section in {None, "application"}) and logo_file and logo_file.filename:
        safe_ext = Path(logo_file.filename).suffix.lower()
        if safe_ext in {".png", ".jpg", ".jpeg", ".svg", ".webp"}:
            LOGO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            file_name = f"logo-{uuid4().hex}{safe_ext}"
            target = LOGO_UPLOAD_DIR / file_name
            content = await logo_file.read()
            target.write_bytes(content)
            settings_payload["application"]["logo_url"] = f"/static/uploads/logos/{file_name}"

    if selected_section == "runtime":
        merged_settings = deepcopy(current_settings)
        app_cfg = (merged_settings.get("application") or {}).copy()
        app_cfg["maintenance_mode"] = settings_payload["application"].get("maintenance_mode")
        app_cfg["maintenance_message"] = settings_payload["application"].get("maintenance_message")
        app_cfg["debug_mode"] = settings_payload["application"].get("debug_mode")
        merged_settings["application"] = app_cfg
        await save_admin_settings(merged_settings)
        await audit_log(
            action="ADMIN_SETTINGS_UPDATED",
            request=request,
            user=_audit_actor(request),
            meta={
                "section": "runtime",
                "section_saved": True,
                "maintenance_mode": app_cfg.get("maintenance_mode"),
                "debug_mode": app_cfg.get("debug_mode"),
            },
        )
        return RedirectResponse("/admin?settings=updated&section=runtime#settings", status_code=303)

    if selected_section:
        merged_settings = deepcopy(current_settings)
        merged_settings[selected_section] = settings_payload[selected_section]
        await save_admin_settings(merged_settings)
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            if selected_section == "backup":
                await configure_backup_schedule(scheduler)
            if selected_section == "application":
                await configure_recurring_schedule(scheduler)
                await configure_backup_schedule(scheduler)
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
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None:
        await configure_backup_schedule(scheduler)
        await configure_recurring_schedule(scheduler)
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


@router.post("/settings/backup/run")
@admin_required
async def admin_run_backup_now(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    try:
        result = await run_backup(actor=_audit_actor(request))
    except Exception as exc:
        await audit_log(
            action="ADMIN_BACKUP_RUN_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"error": str(exc)},
        )
        return JSONResponse({"detail": f"Backup failed: {exc}"}, status_code=400)

    await audit_log(
        action="ADMIN_BACKUP_RUN_COMPLETED",
        request=request,
        user=_audit_actor(request),
        meta={
            "archive_name": result.get("archive_name"),
            "archive_size_bytes": result.get("archive_size_bytes"),
            "collections": result.get("collections"),
            "documents": result.get("documents"),
            "includes_uploads": result.get("includes_uploads"),
        },
    )
    return JSONResponse({"status": "ok", "backup": result, "history": await list_backup_history(8)})


@router.post("/settings/backup/status")
@admin_required
async def admin_backup_status(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    status = await get_backup_status()
    return JSONResponse({"status": "ok", "backup": status})


@router.post("/settings/backup/history")
@admin_required
async def admin_backup_history(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    history = await list_backup_history(8)
    return JSONResponse({"status": "ok", "history": history})


@router.post("/settings/backup/local-history")
@admin_required
async def admin_backup_local_history(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json() if request.headers.get("Content-Type", "").startswith("application/json") else {}
    backup_cfg = _normalize_backup_payload(payload) if payload else None
    try:
        local_backups = await list_local_backups(12, backup_cfg=backup_cfg)
    except Exception as exc:
        return JSONResponse({"detail": f"Local backup scan failed: {exc}"}, status_code=400)
    return JSONResponse({"status": "ok", "local_backups": local_backups})


@router.post("/settings/backup/verify-file")
@admin_required
async def admin_verify_backup_file(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    archive_name = str((payload or {}).get("archive_name") or "").strip()
    backup_cfg = _normalize_backup_payload(payload) if payload else None

    if not archive_name:
        return JSONResponse({"detail": "Backup file is required."}, status_code=400)

    try:
        verified = await verify_local_backup(archive_name=archive_name, backup_cfg=backup_cfg)
    except Exception as exc:
        await audit_log(
            action="ADMIN_BACKUP_FILE_VERIFY_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"archive_name": archive_name, "error": str(exc)},
        )
        return JSONResponse({"detail": f"Verification failed: {exc}"}, status_code=400)

    await audit_log(
        action="ADMIN_BACKUP_FILE_VERIFIED",
        request=request,
        user=_audit_actor(request),
        meta={
            "archive_name": archive_name,
            "verified": verified.get("verified"),
            "sha256": verified.get("sha256"),
            "validation_error": verified.get("validation_error"),
        },
    )
    return JSONResponse({
        "status": "ok",
        "verified_backup": verified,
        "local_backups": await list_local_backups(12, backup_cfg=backup_cfg),
    })


@router.post("/settings/backup/validate")
@admin_required
async def admin_backup_validate(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    backup_cfg = _normalize_backup_payload(payload)
    app_cfg = (payload or {}).get("application") or {}
    timezone_name = str(app_cfg.get("timezone") or "").strip()
    if not timezone_name:
        current_settings = await get_admin_settings()
        timezone_name = str(((current_settings.get("application") or {}).get("timezone") or "Asia/Kolkata")).strip() or "Asia/Kolkata"
    config = describe_backup_config(backup_cfg, timezone_name)
    if config.get("validation_error"):
        return JSONResponse({"detail": config.get("validation_error"), "config": config}, status_code=400)
    return JSONResponse({"status": "ok", "config": config})


@router.post("/settings/backup/delete")
@admin_required
async def admin_delete_backup_now(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    backup_id = str((payload or {}).get("backup_id") or "").strip()

    if not backup_id:
        return JSONResponse({"detail": "Backup id is required."}, status_code=400)

    try:
        result = await delete_backup(run_id=backup_id)
    except Exception as exc:
        await audit_log(
            action="ADMIN_BACKUP_DELETE_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"backup_id": backup_id, "error": str(exc)},
        )
        return JSONResponse({"detail": f"Delete failed: {exc}"}, status_code=400)

    await audit_log(
        action="ADMIN_BACKUP_DELETED",
        request=request,
        user=_audit_actor(request),
        meta=result,
    )
    return JSONResponse({
        "status": "ok",
        "deleted": result,
        "backup": await get_backup_status(),
        "history": await list_backup_history(8),
        "local_backups": await list_local_backups(12),
    })


@router.post("/settings/backup/delete-file")
@admin_required
async def admin_delete_backup_file_now(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    archive_name = str((payload or {}).get("archive_name") or "").strip()
    backup_cfg = _normalize_backup_payload(payload) if payload else None

    if not archive_name:
        return JSONResponse({"detail": "Backup file is required."}, status_code=400)

    try:
        result = await delete_backup_file(archive_name=archive_name, backup_cfg=backup_cfg)
    except Exception as exc:
        await audit_log(
            action="ADMIN_BACKUP_FILE_DELETE_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"archive_name": archive_name, "error": str(exc)},
        )
        return JSONResponse({"detail": f"Delete failed: {exc}"}, status_code=400)

    await audit_log(
        action="ADMIN_BACKUP_FILE_DELETED",
        request=request,
        user=_audit_actor(request),
        meta=result,
    )
    return JSONResponse({
        "status": "ok",
        "deleted": result,
        "backup": await get_backup_status(),
        "history": await list_backup_history(8),
        "local_backups": await list_local_backups(12, backup_cfg=backup_cfg),
    })


@router.post("/settings/backup/restore-file")
@admin_required
async def admin_restore_backup_file_now(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    archive_name = str((payload or {}).get("archive_name") or "").strip()
    create_safety_backup = bool((payload or {}).get("create_safety_backup", True))

    if not archive_name:
        return JSONResponse({"detail": "Backup file is required."}, status_code=400)

    try:
        result = await restore_backup_file(
            archive_name=archive_name,
            actor=_audit_actor(request),
            create_safety_backup=create_safety_backup,
        )
    except Exception as exc:
        await audit_log(
            action="ADMIN_BACKUP_FILE_RESTORE_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"archive_name": archive_name, "error": str(exc), "create_safety_backup": create_safety_backup},
        )
        return JSONResponse({"detail": f"Restore failed: {exc}"}, status_code=400)

    await audit_log(
        action="ADMIN_BACKUP_FILE_RESTORE_COMPLETED",
        request=request,
        user=_audit_actor(request),
        meta={
            "archive_name": archive_name,
            "restored_at": result.get("restored_at"),
            "collections": result.get("collections"),
            "documents": result.get("documents"),
            "uploads": result.get("uploads"),
            "safety_backup": (result.get("safety_backup") or {}).get("archive_name"),
        },
    )
    return JSONResponse({
        "status": "ok",
        "restore": result,
        "backup": await get_backup_status(),
        "history": await list_backup_history(8),
        "local_backups": await list_local_backups(12),
    })


@router.post("/settings/backup/restore")
@admin_required
async def admin_restore_backup_now(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    payload = await request.json()
    backup_id = str((payload or {}).get("backup_id") or "").strip()
    create_safety_backup = bool((payload or {}).get("create_safety_backup", True))

    if not backup_id:
        return JSONResponse({"detail": "Backup id is required."}, status_code=400)

    try:
        result = await restore_backup(
            run_id=backup_id,
            actor=_audit_actor(request),
            create_safety_backup=create_safety_backup,
        )
    except Exception as exc:
        await audit_log(
            action="ADMIN_BACKUP_RESTORE_FAILED",
            request=request,
            user=_audit_actor(request),
            meta={"backup_id": backup_id, "error": str(exc), "create_safety_backup": create_safety_backup},
        )
        return JSONResponse({"detail": f"Restore failed: {exc}"}, status_code=400)

    await audit_log(
        action="ADMIN_BACKUP_RESTORE_COMPLETED",
        request=request,
        user=_audit_actor(request),
        meta={
            "backup_id": backup_id,
            "restored_at": result.get("restored_at"),
            "collections": result.get("collections"),
            "documents": result.get("documents"),
            "uploads": result.get("uploads"),
            "safety_backup": (result.get("safety_backup") or {}).get("archive_name"),
        },
    )
    return JSONResponse({
        "status": "ok",
        "restore": result,
        "backup": await get_backup_status(),
        "history": await list_backup_history(8),
        "local_backups": await list_local_backups(12),
    })


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
        error_code = str(result.get("error") or "").strip()
        if error_code == "no_active_fcm_token":
            detail = (
                "Push test failed: no active FCM token for this account. "
                "Open the app in this browser, allow notifications, then refresh and retry."
            )
        elif error_code == "no_active_subscription":
            detail = (
                "Push test failed: no active Web Push subscription for this account. "
                "Open the app in this browser, allow notifications, then refresh and retry."
            )
        else:
            detail = f"Push test failed: {error_code or 'No active push subscription found for current admin user.'}"
        return JSONResponse({"detail": detail, "result": result}, status_code=400)

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
