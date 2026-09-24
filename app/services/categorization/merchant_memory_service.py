"""Merchant memory persistence and feedback service."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from bson import ObjectId

from app.core.errors import ValidationError
from app.db.mongo import db

UTC = timezone.utc
logger = logging.getLogger(__name__)


def _ensure_user_oid(user_id: str | ObjectId) -> ObjectId:
    if isinstance(user_id, ObjectId):
        return user_id
    if not ObjectId.is_valid(user_id):
        raise ValidationError("Invalid user")
    return ObjectId(user_id)


def _normalize_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


async def lookup(*, user_id: str | ObjectId, cleaned_key: str) -> dict[str, Any] | None:
    user_oid = _ensure_user_oid(user_id)
    key = _normalize_key(cleaned_key)
    if not key:
        return None

    doc = await db.merchant_memory.find_one(
        {"user_id": user_oid, "cleaned_key": key},
        {"_id": 0},
    )
    if not doc:
        doc = await db.merchant_memory.find_one(
            {"user_id": user_oid, "merchant_keyword": key},
            {"_id": 0},
        )
    if not doc:
        logger.debug("merchant memory miss: user_id=%s cleaned_key=%s", str(user_oid), key)
        return None

    await update_usage(user_id=user_oid, cleaned_key=key)
    logger.info("merchant memory hit: user_id=%s cleaned_key=%s", str(user_oid), key)
    return doc


async def learn(
    *,
    user_id: str | ObjectId,
    cleaned_key: str,
    merchant_name: str,
    category: str,
    subcategory: str,
    confidence: float = 0.98,
    learned_from: str = "user",
    category_code: str | None = None,
    subcategory_code: str | None = None,
) -> dict[str, Any]:
    user_oid = _ensure_user_oid(user_id)
    key = _normalize_key(cleaned_key)
    if not key:
        raise ValidationError("cleaned_key is required")
    if not category or not subcategory:
        raise ValidationError("category and subcategory are required")

    now = datetime.now(UTC)
    payload = {
        "user_id": user_oid,
        "cleaned_key": key,
        "merchant_keyword": key,
        "merchant_name": str(merchant_name or key).strip() or key.title(),
        "category": str(category).strip(),
        "subcategory": str(subcategory).strip(),
        "category_code": str(category_code).strip() if category_code else None,
        "subcategory_code": str(subcategory_code).strip() if subcategory_code else None,
        "confidence": float(confidence),
        "learned_from": str(learned_from or "user").strip(),
        "last_used": now,
        "updated_at": now,
    }

    await db.merchant_memory.update_one(
        {"user_id": user_oid, "cleaned_key": key},
        {
            "$set": payload,
            "$setOnInsert": {
                "created_at": now,
            },
            "$inc": {"usage_count": 1},
        },
        upsert=True,
    )
    logger.info("merchant memory learned: user_id=%s cleaned_key=%s", str(user_oid), key)
    return payload


async def update_usage(*, user_id: str | ObjectId, cleaned_key: str) -> None:
    user_oid = _ensure_user_oid(user_id)
    key = _normalize_key(cleaned_key)
    if not key:
        return

    result = await db.merchant_memory.update_one(
        {"user_id": user_oid, "cleaned_key": key},
        {
            "$set": {"last_used": datetime.now(UTC)},
            "$inc": {"usage_count": 1},
        },
    )
    if getattr(result, "modified_count", 0):
        return

    await db.merchant_memory.update_one(
        {"user_id": user_oid, "merchant_keyword": key},
        {
            "$set": {"last_used": datetime.now(UTC)},
            "$inc": {"usage_count": 1},
        },
    )


async def add_alias(*, user_id: str | ObjectId, alias_key: str, cleaned_key: str) -> None:
    user_oid = _ensure_user_oid(user_id)
    alias = _normalize_key(alias_key)
    target = _normalize_key(cleaned_key)
    if not alias or not target:
        raise ValidationError("alias_key and cleaned_key are required")

    await db.merchant_aliases.update_one(
        {"user_id": user_oid, "alias_key": alias},
        {
            "$set": {
                "cleaned_key": target,
                "updated_at": datetime.now(UTC),
            },
            "$setOnInsert": {
                "created_at": datetime.now(UTC),
            },
        },
        upsert=True,
    )
    logger.info("merchant alias saved: user_id=%s alias=%s cleaned_key=%s", str(user_oid), alias, target)


async def record_feedback(
    *,
    user_id: str | ObjectId,
    txn_id: str,
    original_description: str,
    cleaned_key: str,
    old_category: str | None,
    new_category: str,
    old_subcategory: str | None = None,
    new_subcategory: str | None = None,
) -> None:
    user_oid = _ensure_user_oid(user_id)
    key = _normalize_key(cleaned_key)
    if not txn_id:
        return

    await db.categorization_feedback.insert_one(
        {
            "user_id": user_oid,
            "txn_id": str(txn_id),
            "original_description": str(original_description or ""),
            "cleaned_key": key,
            "old_category": old_category,
            "new_category": str(new_category),
            "old_subcategory": old_subcategory,
            "new_subcategory": new_subcategory,
            "timestamp": datetime.now(UTC),
        }
    )
    logger.info("categorization feedback stored: user_id=%s txn_id=%s cleaned_key=%s", str(user_oid), txn_id, key)


__all__ = [
    "add_alias",
    "learn",
    "lookup",
    "record_feedback",
    "update_usage",
]
