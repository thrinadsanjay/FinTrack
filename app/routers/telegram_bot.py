from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.admin_settings import get_admin_settings
from app.services.telegram_transactions import process_telegram_text

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def telegram_webhook(request: Request):
    configured_secret = ""
    payload = await request.json()
    message = (payload or {}).get("message") or {}
    chat = message.get("chat") or {}
    text = str(message.get("text") or "").strip()
    chat_id = str(chat.get("id") or "").strip()

    if not chat_id or not text:
        return JSONResponse({"status": "ignored"})

    settings = await get_admin_settings()
    telegram_cfg = (settings or {}).get("telegram") or {}
    if not telegram_cfg.get("enabled"):
        return JSONResponse({"status": "disabled"})

    configured_secret = str(telegram_cfg.get("webhook_secret") or "").strip()
    if configured_secret:
        incoming_secret = str(request.headers.get("X-Telegram-Bot-Api-Secret-Token") or "").strip()
        if not incoming_secret or not hmac.compare_digest(incoming_secret, configured_secret):
            logger.warning("Rejected Telegram webhook request due to invalid secret token")
            return JSONResponse({"status": "unauthorized"}, status_code=401)

    bot_token = str(telegram_cfg.get("bot_token") or "").strip()
    if not bot_token:
        return JSONResponse({"status": "misconfigured"})

    await process_telegram_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
    )
    return JSONResponse({"status": "ok"})
