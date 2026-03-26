import os
from datetime import datetime, timezone
from copy import deepcopy

from app.core.config import settings
from app.db.mongo import db
from app.helpers.recurring_schedule import legacy_cron_to_time, parse_scheduler_time
from app.helpers.phone import country_iso_from_timezone, timezone_from_country_iso, DEFAULT_PHONE_COUNTRY

SETTINGS_DOC_ID = "admin_settings"
_MAINTENANCE_CACHE_TTL_SECONDS = 15
_maintenance_cache: dict = {
    "expires_at": datetime.fromtimestamp(0, tz=timezone.utc),
    "value": {"enabled": False, "message": ""},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def default_admin_settings() -> dict:
    default_base = str(settings.FT_BASE_URL or "").strip().rstrip("/")
    default_telegram_webhook = (
        str(settings.FT_TELEGRAM_WEBHOOK_URL or "").strip()
        or (f"{default_base}/api/telegram/webhook" if default_base else "")
    )
    scheduler_raw = str(os.getenv("SCHEDULER_RUN_TIME", "05:41") or "05:41").strip() or "05:41"
    try:
        scheduler_hour, scheduler_minute, _ = parse_scheduler_time(scheduler_raw)
        scheduler_run_time = f"{scheduler_hour:02d}:{scheduler_minute:02d}"
    except ValueError:
        scheduler_run_time = "05:41"
    return {
        "application": {
            "enabled": True,
            "app_name": settings.FT_APP_NAME,
            "logo_url": settings.FT_APP_LOGO_URL or "",
            "default_country": country_iso_from_timezone(settings.FT_APP_TIMEZONE or None) or DEFAULT_PHONE_COUNTRY,
            "timezone": timezone_from_country_iso(country_iso_from_timezone(settings.FT_APP_TIMEZONE or None)),
            "support_email": settings.FT_SUPPORT_EMAIL,
            "support_phone": settings.FT_SUPPORT_PHONE,
            "scheduler_run_time": scheduler_run_time,
            "maintenance_mode": bool(settings.FT_MAINTENANCE_MODE),
            "maintenance_message": settings.FT_MAINTENANCE_MESSAGE or "",
            "debug_mode": bool(settings.FT_DEBUG_LOG),
        },
        "smtp": {
            "enabled": bool(settings.FT_SMTP_ENABLED or (settings.FT_SMTP_HOST and settings.FT_SMTP_PORT)),
            "host": settings.FT_SMTP_HOST or "",
            "port": str(settings.FT_SMTP_PORT or ""),
            "username": settings.FT_SMTP_USERNAME or "",
            "password": settings.FT_SMTP_PASSWORD or "",
            "from_email": settings.FT_SMTP_FROM or "",
            "tls": bool(settings.FT_SMTP_TLS),
        },
        "telegram": {
            "enabled": bool(settings.FT_TELEGRAM_ENABLED),
            "bot_username": settings.FT_TELEGRAM_BOT_USERNAME or "",
            "bot_token": settings.FT_TELEGRAM_BOT_TOKEN or "",
            "webhook_url": default_telegram_webhook,
            "webhook_secret": settings.FT_TELEGRAM_WEBHOOK_SECRET or "",
            "polling_enabled": bool(settings.FT_TELEGRAM_POLLING_ENABLED),
        },
        "push_notifications": {
            "enabled": bool(settings.FT_PUSH_ENABLED),
            "provider": "firebase",
            "vapid_public_key": settings.FT_PUSH_VAPID_PUBLIC_KEY or "",
            "firebase_service_account_json": settings.FT_PUSH_FIREBASE_SERVICE_ACCOUNT_JSON or "",
            "firebase_config": {
                "apiKey": settings.FT_PUSH_FIREBASE_API_KEY or "",
                "authDomain": settings.FT_PUSH_FIREBASE_AUTH_DOMAIN or "",
                "projectId": settings.FT_PUSH_FIREBASE_PROJECT_ID or "",
                "storageBucket": settings.FT_PUSH_FIREBASE_STORAGE_BUCKET or "",
                "messagingSenderId": settings.FT_PUSH_FIREBASE_MESSAGING_SENDER_ID or "",
                "appId": settings.FT_PUSH_FIREBASE_APP_ID or "",
                "measurementId": settings.FT_PUSH_FIREBASE_MEASUREMENT_ID or "",
            },
        },
        "authentication": {
            "enabled": bool(settings.FT_AUTH_ENABLED),
            "provider": settings.FT_AUTH_PROVIDER or "keycloak",
            "keycloak_url": settings.FT_KEYCLOAK_URL,
            "realm": settings.FT_KEYCLOAK_REALM,
            "client_id": settings.FT_CLIENT_ID,
            "allow_local_login": bool(settings.FT_AUTH_ALLOW_LOCAL_LOGIN),
            "allow_google_login": True,
            "allow_telegram_login": bool(settings.FT_TELEGRAM_ENABLED),
            "default_telegram_country": country_iso_from_timezone(settings.FT_APP_TIMEZONE or None) or DEFAULT_PHONE_COUNTRY,
        },
        "database": {
            "enabled": bool(settings.FT_DB_ENABLED),
            "mongo_uri": settings.FT_MONGO_URI,
            "mongo_db_name": settings.FT_MONGO_DB_NAME,
        },
        "backup": {
            "enabled": bool(settings.FT_BACKUP_ENABLED),
            "provider": settings.FT_BACKUP_PROVIDER or "filesystem",
            "schedule_time": settings.FT_BACKUP_SCHEDULE_TIME or legacy_cron_to_time(settings.FT_BACKUP_SCHEDULE_CRON) or "02:00",
            "schedule_cron": settings.FT_BACKUP_SCHEDULE_CRON or "0 2 * * *",
            "retention_days": settings.FT_BACKUP_RETENTION_DAYS or "7",
            "destination": settings.FT_BACKUP_DESTINATION or "/backups/fintrack",
        },
    }


def _deep_merge(base: dict, patch: dict) -> dict:
    merged = deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


async def get_admin_settings_doc() -> dict | None:
    return await db.app_settings.find_one({"_id": SETTINGS_DOC_ID})


async def get_admin_settings() -> dict:
    defaults = default_admin_settings()
    doc = await get_admin_settings_doc()
    overrides = (doc or {}).get("values") or {}
    return _deep_merge(defaults, overrides)


async def get_maintenance_state(force_refresh: bool = False) -> dict:
    now = _now()
    if not force_refresh and now < _maintenance_cache["expires_at"]:
        return _maintenance_cache["value"]

    cfg = await get_admin_settings()
    app_cfg = (cfg or {}).get("application") or {}
    message = (app_cfg.get("maintenance_message") or "").strip()
    state = {
        "enabled": bool(app_cfg.get("maintenance_mode")),
        "message": message,
    }
    _maintenance_cache["value"] = state
    _maintenance_cache["expires_at"] = datetime.fromtimestamp(
        now.timestamp() + _MAINTENANCE_CACHE_TTL_SECONDS, tz=timezone.utc
    )
    return state


async def save_admin_settings(values: dict) -> None:
    await db.app_settings.update_one(
        {"_id": SETTINGS_DOC_ID},
        {
            "$set": {
                "values": values,
                "updated_at": _now(),
            },
            "$setOnInsert": {"created_at": _now()},
        },
        upsert=True,
    )
    _maintenance_cache["expires_at"] = datetime.fromtimestamp(0, tz=timezone.utc)
