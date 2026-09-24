"""Shared OpenAI client helpers. Narratives are optional and must fail quietly."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_transport_down = False
_clients: dict[tuple, Any] = {}
_CONNECT_MARKERS = (
    "name resolution",
    "temporary failure",
    "connection error",
    "connecterror",
    "apiconnectionerror",
    "connecttimeout",
    "timed out",
    "timeout",
    "network is unreachable",
    "errno -3",
)


def openai_configured() -> bool:
    return bool(str(os.getenv("OPENAI_API_KEY") or "").strip())


def ai_transport_ok() -> bool:
    return not _transport_down


def mark_ai_unreachable(reason: str = "") -> None:
    global _transport_down
    if not _transport_down:
        detail = f": {reason}" if reason else ""
        logger.warning("AI provider unreachable; optional narratives disabled until restart%s", detail)
    _transport_down = True


def is_ai_connect_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _CONNECT_MARKERS)


def openai_client(**kwargs: Any):
    """Async client: callers must `await client.chat.completions.create(...)`
    so a slow provider never blocks the event loop (requests, schedulers, bot)."""
    from openai import AsyncOpenAI

    opts: dict[str, Any] = {"timeout": 8.0, "max_retries": 0}
    opts.update(kwargs)
    api_key = os.getenv("OPENAI_API_KEY")
    # Reuse one client (and its connection pool) per key/options combination.
    cache_key = (api_key, tuple(sorted(opts.items())))
    client = _clients.get(cache_key)
    if client is None:
        client = AsyncOpenAI(api_key=api_key, **opts)
        _clients[cache_key] = client
    return client


def log_ai_failure(action: str, exc: BaseException) -> None:
    if is_ai_connect_error(exc):
        mark_ai_unreachable(str(exc))
        return
    logger.exception("%s failed", action)
