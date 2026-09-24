"""Merchant key extraction with alias resolution."""

from __future__ import annotations

import logging
from typing import Any

from bson import ObjectId

from app.core.errors import ValidationError
from app.db.mongo import db

logger = logging.getLogger(__name__)


def _ensure_user_oid(user_id: str | ObjectId) -> ObjectId:
    if isinstance(user_id, ObjectId):
        return user_id
    if not ObjectId.is_valid(user_id):
        raise ValidationError("Invalid user")
    return ObjectId(user_id)


def _normalize_key(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _alias_candidates(cleaned_description: str) -> list[str]:
    tokens = _normalize_key(cleaned_description).split()
    candidates: list[str] = []
    for width in range(len(tokens), 0, -1):
        candidate = " ".join(tokens[:width])
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


async def extract_merchant_key(*, user_id: str | ObjectId, cleaned_description: str) -> str:
    """
    Return the standardized merchant key for a cleaned description.

    Lookup order:
    1. merchant_aliases exact match on full/leading phrases
    2. fallback to the first token from cleaned_description
    """

    normalized = _normalize_key(cleaned_description)
    if not normalized:
        return ""

    user_oid = _ensure_user_oid(user_id)
    candidates = _alias_candidates(normalized)
    for candidate in candidates:
        alias = await db.merchant_aliases.find_one(
            {"user_id": user_oid, "alias_key": candidate},
        )
        if alias and alias.get("cleaned_key"):
            resolved = _normalize_key(alias.get("cleaned_key"))
            logger.info("merchant alias hit: alias=%s cleaned_key=%s", alias.get("alias_key"), resolved)
            return resolved

    return normalized.split()[0]


__all__ = ["extract_merchant_key"]
