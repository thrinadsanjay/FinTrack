"""Strip secrets and foreign-user fields before any AI payload is built."""

from __future__ import annotations

from typing import Any

SECRET_KEYS = {
    "password",
    "password_hash",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "bot_token",
    "telegram_bot_token",
    "api_key",
    "apikey",
    "secret",
    "client_secret",
    "oauth_secret",
    "session_secret",
    "csrf_token",
    "private_key",
    "service_account",
    "firebase",
    "vapid",
    "credential",
    "otp",
    "telegram_otp",
}

MAX_TOOL_CHARS = 8000
MAX_TRANSACTIONS = 40

ALLOWED_TOOL_NAMES = {
    "get_balance",
    "get_transactions",
    "get_spending_by_category",
    "get_cash_flow",
    "get_forecast",
    "get_safe_to_spend",
    "get_net_worth",
    "get_credit_cards",
    "get_upcoming_bills",
    "get_goals",
    "get_financial_health",
}


def authorize_tool_call(*, user_id: str, name: str) -> dict | None:
    if not str(user_id or "").strip():
        return {"error": "unauthorized"}
    if name not in ALLOWED_TOOL_NAMES:
        return {"error": "unknown_tool"}
    return None


def is_secret_key(key: str) -> bool:
    lowered = str(key or "").strip().lower()
    if lowered in SECRET_KEYS:
        return True
    return any(part in lowered for part in ("secret", "token", "password", "credential"))


def sanitize_for_ai(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return None
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if is_secret_key(str(key)):
                continue
            if str(key).lower() in {"user_id", "chat_id"} and depth > 0:
                # Keep ids only at the top-level tool envelope, never nested user rows.
                continue
            clean[str(key)] = sanitize_for_ai(item, depth=depth + 1)
        return clean
    if isinstance(value, list):
        return [sanitize_for_ai(item, depth=depth + 1) for item in value[:MAX_TRANSACTIONS]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = value
        if isinstance(text, str) and len(text) > 500:
            return text[:500]
        return text
    return str(value)[:200]


def clip_tool_result(payload: Any) -> Any:
    cleaned = sanitize_for_ai(payload)
    encoded = str(cleaned)
    if len(encoded) > MAX_TOOL_CHARS:
        if isinstance(cleaned, dict) and "items" in cleaned and isinstance(cleaned["items"], list):
            cleaned["items"] = cleaned["items"][:12]
            cleaned["truncated"] = True
        elif isinstance(cleaned, list):
            return cleaned[:12]
    return cleaned


def hallucination_guard_text() -> str:
    return (
        "Use only numbers returned by tools. If a tool result is empty or missing, "
        "say the data is not available. Never invent balances, merchants, or dates. "
        "Do not give investment, loan, tax, or product recommendations."
    )
