from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.services.admin_settings import get_admin_settings
from app.services.telegram import get_updates, get_webhook_info
from app.services.telegram_transactions import process_telegram_text

logger = logging.getLogger(__name__)

_poll_lock = asyncio.Lock()
_last_update_id: int | None = None
_last_poll_at: datetime | None = None
_last_poll_error: str = ""
_last_processed_updates: int = 0
_last_processed_messages: int = 0
_last_config_enabled: bool = False
_last_config_polling_enabled: bool = False
_last_config_has_token: bool = False
_last_webhook_url: str = ""


async def run_telegram_poll_once() -> None:
    global _last_update_id, _last_poll_at, _last_poll_error, _last_processed_updates, _last_processed_messages
    global _last_config_enabled, _last_config_polling_enabled, _last_config_has_token, _last_webhook_url
    if _poll_lock.locked():
        return

    async with _poll_lock:
        _last_poll_at = datetime.now(timezone.utc)
        _last_poll_error = ""
        _last_processed_updates = 0
        _last_processed_messages = 0
        settings = await get_admin_settings()
        telegram_cfg = (settings or {}).get("telegram") or {}
        _last_config_enabled = bool(telegram_cfg.get("enabled"))
        _last_config_polling_enabled = bool(telegram_cfg.get("polling_enabled"))

        if not _last_config_enabled:
            _last_poll_error = "Telegram integration is disabled."
            return
        if not _last_config_polling_enabled:
            _last_poll_error = "Polling fallback is disabled."
            return

        bot_token = str(telegram_cfg.get("bot_token") or "").strip()
        _last_config_has_token = bool(bot_token)
        if not bot_token:
            _last_poll_error = "Telegram bot token is missing."
            return

        try:
            webhook_info = await get_webhook_info(bot_token=bot_token)
            webhook_url = str(((webhook_info or {}).get("result") or {}).get("url") or "").strip()
            _last_webhook_url = webhook_url
            if webhook_url:
                logger.info("Telegram polling skipped because webhook is active: %s", webhook_url)
                _last_poll_error = "Webhook is active; polling skipped."
                return
        except Exception as exc:
            logger.warning("Telegram polling webhook check failed: %s", exc)
            _last_poll_error = f"Webhook check failed: {exc}"
            return

        try:
            payload = await get_updates(
                bot_token=bot_token,
                offset=(_last_update_id + 1) if _last_update_id is not None else None,
                limit=30,
                timeout=0,
            )
        except Exception as exc:
            logger.warning("Telegram polling getUpdates failed: %s", exc)
            _last_poll_error = f"getUpdates failed: {exc}"
            return

        if not bool((payload or {}).get("ok")):
            description = str((payload or {}).get("description") or "").lower()
            if "terminated by other getupdates request" in description:
                logger.warning("Telegram polling conflict: another poller is active.")
                _last_poll_error = "Conflict: another getUpdates poller is active."
            elif description:
                logger.warning("Telegram polling error: %s", description)
                _last_poll_error = description
            return

        updates = list((payload or {}).get("result") or [])
        _last_processed_updates = len(updates)
        if not updates:
            return

        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                _last_update_id = max(_last_update_id or update_id, update_id)
            message = (update or {}).get("message") or {}
            chat = message.get("chat") or {}
            text = str(message.get("text") or "").strip()
            chat_id = str(chat.get("id") or "").strip()
            if not chat_id or not text:
                continue
            _last_processed_messages += 1
            try:
                await process_telegram_text(bot_token=bot_token, chat_id=chat_id, text=text)
            except Exception as exc:
                logger.warning("Telegram polling message processing failed (chat=%s): %s", chat_id, exc)
                _last_poll_error = f"Processing failed for chat {chat_id}: {exc}"


def get_telegram_poll_status() -> dict:
    return {
        "last_update_id": _last_update_id,
        "last_poll_at": _last_poll_at.isoformat() if _last_poll_at else None,
        "last_error": _last_poll_error,
        "processed_updates": _last_processed_updates,
        "processed_messages": _last_processed_messages,
        "is_running": _poll_lock.locked(),
        "config_enabled": _last_config_enabled,
        "config_polling_enabled": _last_config_polling_enabled,
        "config_has_token": _last_config_has_token,
        "webhook_url": _last_webhook_url,
    }
