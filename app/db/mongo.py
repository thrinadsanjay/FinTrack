import logging
import os
from typing import Any, Awaitable, Callable, TypeVar

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorClientSession
from app.core.config import settings

logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(settings.FT_MONGO_URI)
db = client[settings.FT_MONGO_DB_NAME]

T = TypeVar("T")

# None = not probed yet. Multi-document transactions need a replica set or mongos.
_transactions_supported: bool | None = None


async def supports_transactions() -> bool:
    """
    FT_MONGO_TRANSACTIONS: "auto" (default) probes the server once,
    "on" forces transactions, "off" disables them.
    """
    global _transactions_supported
    if _transactions_supported is not None:
        return _transactions_supported

    mode = str(os.getenv("FT_MONGO_TRANSACTIONS", "auto")).strip().lower()
    if mode in ("on", "true", "1"):
        _transactions_supported = True
    elif mode in ("off", "false", "0"):
        _transactions_supported = False
    else:
        try:
            hello = await client.admin.command("hello")
            _transactions_supported = bool(hello.get("setName")) or hello.get("msg") == "isdbgrid"
        except Exception:
            logger.exception("Could not probe MongoDB topology; running without transactions")
            _transactions_supported = False
        if not _transactions_supported:
            logger.warning(
                "MongoDB is a standalone server: ledger writes use single-document "
                "atomic updates with compensation instead of transactions. "
                "Run MongoDB as a replica set to enable full atomicity."
            )
    return _transactions_supported


async def run_atomic(fn: Callable[[AsyncIOMotorClientSession | None], Awaitable[T]]) -> T:
    """
    Run fn(session) inside a multi-document transaction when the server supports it,
    retrying on transient errors. Otherwise fn(None) runs directly, so fn must pass
    `session=session` to every write and keep its own writes compensating.
    """
    if not await supports_transactions():
        return await fn(None)

    async with await client.start_session() as session:
        return await session.with_transaction(fn)


def reset_transaction_support_cache(value: Any = None) -> None:
    """Test hook: force (or clear) the cached topology probe."""
    global _transactions_supported
    _transactions_supported = value
