from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId

from app.core.http import get_async_http_client
from app.db.mongo import db
from app.services.admin_settings import get_admin_settings

logger = logging.getLogger(__name__)

_CFG_CACHE_TTL_SECONDS = 30
_cfg_cache: dict = {
    "expires_at": datetime.fromtimestamp(0, tz=timezone.utc),
    "value": {
        "enabled": False,
        "bot_token": "",
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_delivery_config() -> dict:
    now = _now()
    if now < _cfg_cache["expires_at"]:
        return _cfg_cache["value"]

    settings = await get_admin_settings()
    telegram_cfg = (settings or {}).get("telegram") or {}
    value = {
        "enabled": bool(telegram_cfg.get("enabled")),
        "bot_token": str(telegram_cfg.get("bot_token") or "").strip(),
    }
    _cfg_cache["value"] = value
    _cfg_cache["expires_at"] = datetime.fromtimestamp(now.timestamp() + _CFG_CACHE_TTL_SECONDS, tz=timezone.utc)
    return value


def is_mirror_eligible(*, key: str, notif_type: str, message: str) -> bool:
    k = str(key or "")
    t = str(notif_type or "").lower()
    m = str(message or "").lower()

    if k.startswith("scheduled_today:"):
        return True
    if k.startswith("low_balance:") or k.startswith("balance_threshold:"):
        return True
    if k.startswith("recurring_failed:") or k.startswith("tx_failed:") or k.startswith("failed_tx_retry_failed:"):
        return True
    if t in {"warning", "critical"} and "insufficient" in m:
        return True
    return False


def _telegram_prefix(notif_type: str) -> str:
    t = str(notif_type or "").lower()
    if t == "critical":
        return "[CRITICAL]"
    if t == "warning":
        return "[WARNING]"
    return "[ALERT]"


async def send_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    reply_markup: dict | None = None,
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with get_async_http_client() as client:
        response = await client.post(url, json=payload)
        payload: dict = {}
        try:
            payload = response.json()
        except Exception:
            payload = {}
        ok = bool(payload.get("ok"))
        if response.status_code >= 400 or not ok:
            description = str(payload.get("description") or "").strip() or f"HTTP {response.status_code}"
            # Fallback: if keyboard markup fails, retry as plain text so user still gets response.
            if reply_markup and ("reply markup" in description.lower() or "keyboard" in description.lower()):
                retry_response = await client.post(url, json={"chat_id": chat_id, "text": text})
                retry_payload: dict = {}
                try:
                    retry_payload = retry_response.json()
                except Exception:
                    retry_payload = {}
                retry_ok = bool(retry_payload.get("ok"))
                if retry_response.status_code < 400 and retry_ok:
                    return
                retry_description = str(retry_payload.get("description") or "").strip() or f"HTTP {retry_response.status_code}"
                raise RuntimeError(retry_description)
            raise RuntimeError(description)


async def send_notification_alert(
    *,
    user_id: ObjectId,
    key: str,
    notif_type: str,
    title: str,
    message: str,
) -> bool:
    if not is_mirror_eligible(key=key, notif_type=notif_type, message=message):
        return False

    cfg = await _get_delivery_config()
    if not cfg.get("enabled") or not cfg.get("bot_token"):
        return False

    user = await db.users.find_one({"_id": user_id}, {"telegram_chat_id": 1})
    chat_id = str((user or {}).get("telegram_chat_id") or "").strip()
    if not chat_id:
        return False

    text = f"{_telegram_prefix(notif_type)} {title}\n{message}"
    try:
        await send_message(bot_token=str(cfg["bot_token"]), chat_id=chat_id, text=text)
        return True
    except Exception as exc:
        logger.warning("Telegram alert send failed for user %s key=%s: %s", str(user_id), key, exc)
        return False


async def set_webhook(
    *,
    bot_token: str,
    webhook_url: str,
    secret_token: str | None = None,
) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {"url": webhook_url}
    if secret_token:
        payload["secret_token"] = secret_token
    async with get_async_http_client() as client:
        response = await client.post(url, json=payload)
    return response.json()


async def get_webhook_info(*, bot_token: str) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    async with get_async_http_client() as client:
        response = await client.get(url)
    return response.json()


async def delete_webhook(*, bot_token: str, drop_pending_updates: bool = False) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
    async with get_async_http_client() as client:
        response = await client.post(url, json={"drop_pending_updates": bool(drop_pending_updates)})
    return response.json()


async def get_updates(*, bot_token: str, offset: int | None = None, limit: int = 50, timeout: int = 0) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {
        "limit": max(1, min(int(limit), 100)),
        "timeout": max(0, min(int(timeout), 50)),
    }
    if offset is not None:
        params["offset"] = int(offset)
    async with get_async_http_client() as client:
        response = await client.get(url, params=params)
    return response.json()
