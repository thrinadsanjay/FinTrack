from datetime import datetime, timezone
from copy import deepcopy

from app.core.config import settings
from app.db.mongo import db

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
    default_telegram_webhook = f"{default_base}/api/telegram/webhook" if default_base else ""
    return {
        "application": {
            "enabled": True,
            "app_name": settings.FT_APP_NAME,
            "logo_url": "",
            "support_email": settings.FT_SUPPORT_EMAIL,
            "support_phone": settings.FT_SUPPORT_PHONE,
            "maintenance_mode": False,
            "maintenance_message": "",
            "debug_mode": bool(settings.FT_DEBUG_LOG),
        },
        "smtp": {
            "enabled": bool(settings.FT_SMTP_HOST and settings.FT_SMTP_PORT),
            "host": settings.FT_SMTP_HOST or "",
            "port": str(settings.FT_SMTP_PORT or ""),
            "username": settings.FT_SMTP_USERNAME or "",
            "password": "",
            "from_email": settings.FT_SMTP_FROM or "",
            "tls": bool(settings.FT_SMTP_TLS),
        },
        "telegram": {
            "enabled": False,
            "bot_username": "",
            "bot_token": "",
            "webhook_url": default_telegram_webhook,
            "webhook_secret": "",
            "polling_enabled": False,
        },
        "push_notifications": {
            "enabled": False,
            "provider": "webpush",
            "vapid_public_key": "",
            "vapid_private_key": "",
        },
        "authentication": {
            "enabled": True,
            "provider": "keycloak",
            "keycloak_url": settings.FT_KEYCLOAK_URL,
            "realm": settings.FT_KEYCLOAK_REALM,
            "client_id": settings.FT_CLIENT_ID,
            "allow_local_login": True,
        },
        "database": {
            "enabled": True,
            "mongo_uri": settings.FT_MONGO_URI,
            "mongo_db_name": settings.FT_MONGO_DB_NAME,
        },
        "backup": {
            "enabled": False,
            "provider": "filesystem",
            "schedule_cron": "0 2 * * *",
            "retention_days": "7",
            "destination": "/backups/fintrack",
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
