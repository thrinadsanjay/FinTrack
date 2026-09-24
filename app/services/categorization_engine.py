"""
Smart categorization engine.

This service sits above narration parsing and below transaction creation.
It accepts a normalized merchant/description payload and tries four layers:

1. merchant_memory collection
2. past transaction similarity
3. merchant_rules collection
4. confidence assembly

Expected input:
    {
        "clean_description": "dmart bangalore",
        "merchant": "dmart",
        "tokens": ["dmart", "bangalore"],
        "mode": "upi",
        "amount": 750.0,
        # optional:
        "type": "debit" | "credit" | "transfer",
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import logging
import re
from typing import Any

from bson import ObjectId

from app.core.errors import ValidationError
from app.db.mongo import db
from app.helpers.money import round_money
from app.services.categorization.description_cleaner import clean_description as clean_memory_description
from app.services.categorization.merchant_extractor import extract_merchant_key
from app.services.categorization.merchant_memory_service import learn as learn_merchant_memory
from app.services.categorization.merchant_memory_service import lookup as lookup_merchant_memory
from app.utils.statement_narration_parser import parse_narration

TOKEN_RE = re.compile(r"[a-z0-9]+")
MAX_HISTORY_CANDIDATES = 40
MIN_HISTORY_SIMILARITY = 0.58
logger = logging.getLogger(__name__)

USER_NAME_STOPWORDS = {
    "user",
    "account",
    "bank",
    "gmail",
    "yahoo",
    "outlook",
    "mail",
    "com",
    "in",
}
SELF_TRANSFER_HINTS = {
    "self",
    "own",
    "transfer",
    "to",
    "from",
    "acct",
    "account",
    "a/c",
}
AUTO_LEARN_STOPWORDS = {
    "payment",
    "upi",
    "bank",
    "txn",
    "transfer",
    "received",
    "sent",
    "credit",
    "debit",
}

_USER_NAME_PARTS_CACHE: dict[str, set[str]] = {}

BUILTIN_KEYWORD_RULES: tuple[dict[str, str], ...] = (
    {"keywords": ("swiggy", "zomato", "dominos", "pizza", "kfc", "mcdonald"), "type": "debit", "category_code": "food", "subcategory_code": "dining_out"},
    {"keywords": ("zepto", "blinkit", "bigbasket", "instamart", "grofers", "dmart"), "type": "debit", "category_code": "food", "subcategory_code": "groceries"},
    {"keywords": ("bakery", "bakers", "cake", "pastry", "sweets"), "type": "debit", "category_code": "food", "subcategory_code": "snacks"},
    {"keywords": ("amazon", "flipkart", "meesho", "ajio"), "type": "debit", "category_code": "shopping", "subcategory_code": "other"},
    {"keywords": ("myntra", "zara", "lifestyle"), "type": "debit", "category_code": "shopping", "subcategory_code": "clothing"},
    {"keywords": ("store", "mart", "shop", "traders"), "type": "debit", "category_code": "shopping", "subcategory_code": "other"},
    {"keywords": ("uber", "ola", "rapido"), "type": "debit", "category_code": "transport", "subcategory_code": "taxi"},
    {"keywords": ("bus", "redbus", "abhibus", "tsrtc", "apsrtc", "intrcity", "srs travels"), "type": "debit", "category_code": "transport", "subcategory_code": "public_transport"},
    {"keywords": ("irctc", "railway", "train"), "type": "debit", "category_code": "transport", "subcategory_code": "public_transport"},
    {"keywords": ("bookmyshow", "pvr", "inox", "movie"), "type": "debit", "category_code": "entertainment", "subcategory_code": "movies"},
    {"keywords": ("netflix", "prime", "hotstar", "spotify", "youtube"), "type": "debit", "category_code": "entertainment", "subcategory_code": "subscriptions"},
    {"keywords": ("electricity", "epdcl", "apepdcl", "tsspdcl", "bescom", "tneb", "mseb"), "type": "debit", "category_code": "utilities", "subcategory_code": "electricity"},
    {"keywords": ("internet", "broadband", "wifi"), "type": "debit", "category_code": "utilities", "subcategory_code": "internet"},
    {"keywords": ("recharge", "airtel", "jio", "vi", "vodafone", "idea", "bsnl"), "type": "debit", "category_code": "utilities", "subcategory_code": "mobile"},
    {"keywords": ("home loan", "housing loan"), "type": "debit", "category_code": "loan", "subcategory_code": "home_loan"},
    {"keywords": ("personal loan",), "type": "debit", "category_code": "loan", "subcategory_code": "personal_loan"},
    {"keywords": ("loan emi", "emi", "loan"), "type": "debit", "category_code": "loan", "subcategory_code": "other_loans"},
)


@dataclass(slots=True)
class MatchResult:
    layer: str
    category: dict[str, str] | None = None
    subcategory: dict[str, str] | None = None
    score: float = 0.0
    metadata: dict[str, Any] | None = None


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _phrase_in_text(phrase: str, text: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return False
    pattern = r"\b" + re.escape(normalized_phrase).replace(r"\ ", r"\s+") + r"\b"
    return re.search(pattern, text) is not None


def _rule_keywords(rule: dict[str, Any]) -> list[str]:
    raw = rule.get("keywords")
    keywords: list[str] = []
    if isinstance(raw, (list, tuple, set)):
        keywords.extend(_normalize_text(item) for item in raw)
    else:
        keywords.append(_normalize_text(rule.get("keyword")))
    return [kw for kw in keywords if kw]


def _normalize_tokens(tokens: list[Any] | tuple[Any, ...] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens or []:
        normalized = _normalize_text(token)
        if not normalized:
            continue
        for piece in TOKEN_RE.findall(normalized):
            if len(piece) < 2 or piece in seen:
                continue
            out.append(piece)
            seen.add(piece)
    return out


def _candidate_keywords(payload: dict[str, Any]) -> list[str]:
    merchant = _normalize_text(payload.get("merchant"))
    clean_description = _normalize_text(payload.get("clean_description"))
    tokens = _normalize_tokens(payload.get("tokens"))

    ordered: list[str] = []
    seen: set[str] = set()
    for value in [merchant, *tokens, clean_description]:
        if not value or value in seen:
            continue
        ordered.append(value)
        seen.add(value)
    return ordered


def _ensure_user_oid(user_id: str | ObjectId) -> ObjectId:
    if isinstance(user_id, ObjectId):
        return user_id
    if not ObjectId.is_valid(user_id):
        raise ValidationError("Invalid user")
    return ObjectId(user_id)


def _category_pair(
    *,
    category_code: str | None,
    category_name: str | None,
    subcategory_code: str | None,
    subcategory_name: str | None,
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    category = None
    subcategory = None
    if category_code:
        category = {
            "code": str(category_code),
            "name": str(category_name or category_code),
        }
    if subcategory_code:
        subcategory = {
            "code": str(subcategory_code),
            "name": str(subcategory_name or subcategory_code),
        }
    return category, subcategory


async def _resolve_category_pair(
    *,
    category_code: str | None,
    subcategory_code: str | None,
    tx_type: str | None = None,
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    if not category_code or not subcategory_code:
        return None, None

    query: dict[str, Any] = {
        "code": str(category_code),
        "is_system": True,
        "subcategories.code": str(subcategory_code),
    }
    if tx_type:
        query["type"] = str(tx_type)

    category_doc = await db.categories.find_one(
        query,
        {"_id": 0, "code": 1, "name": 1, "subcategories": 1},
    )
    if not category_doc and tx_type is None:
        category_doc = await db.categories.find_one(
            {
                "code": str(category_code),
                "subcategories.code": str(subcategory_code),
                "is_system": True,
            },
            {"_id": 0, "code": 1, "name": 1, "subcategories": 1},
        )
    if not category_doc:
        return _category_pair(
            category_code=category_code,
            category_name=None,
            subcategory_code=subcategory_code,
            subcategory_name=None,
        )

    matched_sub = next(
        (
            sub
            for sub in category_doc.get("subcategories", [])
            if str(sub.get("code")) == str(subcategory_code)
        ),
        None,
    )
    return _category_pair(
        category_code=str(category_doc.get("code") or category_code),
        category_name=str(category_doc.get("name") or category_code),
        subcategory_code=str(matched_sub.get("code") or subcategory_code) if matched_sub else str(subcategory_code),
        subcategory_name=str(matched_sub.get("name") or subcategory_code) if matched_sub else None,
    )


def _amount_matches(rule: dict[str, Any], amount: float) -> bool:
    min_amount = rule.get("min_amount")
    max_amount = rule.get("max_amount")
    if min_amount is not None and amount < float(min_amount):
        return False
    if max_amount is not None and amount > float(max_amount):
        return False
    return True


def _mode_matches(rule: dict[str, Any], mode: str) -> bool:
    rule_mode = _normalize_text(rule.get("mode"))
    return not rule_mode or rule_mode == _normalize_text(mode)


def _keyword_matches(rule: dict[str, Any], keywords: list[str], clean_description: str) -> bool:
    rule_keyword = _normalize_text(rule.get("keyword"))
    if not rule_keyword:
        return False
    return rule_keyword in keywords or rule_keyword in clean_description


def _extract_tx_tokens(description: str, merchant: str | None = None) -> list[str]:
    tokens = _normalize_tokens(TOKEN_RE.findall(_normalize_text(description)))
    if merchant:
        merchant_norm = _normalize_text(merchant)
        if merchant_norm and merchant_norm not in tokens:
            return [merchant_norm, *tokens]
    return tokens


def _similarity_score(source_description: str, candidate_description: str, source_tokens: list[str]) -> float:
    source_clean = _normalize_text(source_description)
    candidate_clean = _normalize_text(candidate_description)
    if not source_clean or not candidate_clean:
        return 0.0

    seq_score = SequenceMatcher(None, source_clean, candidate_clean).ratio()
    candidate_tokens = set(_extract_tx_tokens(candidate_clean))
    source_token_set = set(source_tokens)
    overlap = len(source_token_set & candidate_tokens)
    union = len(source_token_set | candidate_tokens) or 1
    token_score = overlap / union
    return (seq_score * 0.55) + (token_score * 0.45)


async def _match_merchant_memory(
    *,
    user_oid: ObjectId,
    keywords: list[str],
    tx_type: str | None,
) -> MatchResult | None:
    if not keywords:
        return None
    cleaned_description = clean_memory_description(" ".join(keywords))
    merchant_key = await extract_merchant_key(user_id=user_oid, cleaned_description=cleaned_description)
    if not merchant_key:
        return None

    doc = await lookup_merchant_memory(user_id=user_oid, cleaned_key=merchant_key)
    if not doc:
        return None

    category, subcategory = _category_pair(
        category_code=doc.get("category_code"),
        category_name=doc.get("category"),
        subcategory_code=doc.get("subcategory_code"),
        subcategory_name=doc.get("subcategory"),
    )
    if not category or not subcategory:
        return None

    return MatchResult(
        layer="merchant_memory",
        category=category,
        subcategory=subcategory,
        score=1.0,
        metadata={"matched_keyword": merchant_key},
    )


async def _match_past_transactions(
    *,
    user_oid: ObjectId,
    clean_description: str,
    merchant: str | None,
    tokens: list[str],
    tx_type: str | None,
) -> MatchResult | None:
    if not clean_description:
        return None

    search_terms = [merchant, *tokens[:4]]
    search_terms = [term for term in search_terms if term]
    if not search_terms:
        search_terms = clean_description.split()[:3]
    if not search_terms:
        return None

    regex = "|".join(re.escape(term) for term in search_terms)
    query: dict[str, Any] = {
        "user_id": user_oid,
        "deleted_at": None,
        "category.code": {"$exists": True, "$ne": None},
        "subcategory.code": {"$exists": True, "$ne": None},
        "description": {"$regex": regex, "$options": "i"},
    }
    if tx_type:
        query["type"] = tx_type

    cursor = (
        db.transactions.find(
            query,
            {
                "description": 1,
                "merchant": 1,
                "category": 1,
                "subcategory": 1,
                "created_at": 1,
            },
        )
        .sort([("created_at", -1)])
        .limit(MAX_HISTORY_CANDIDATES)
    )
    docs = await cursor.to_list(length=MAX_HISTORY_CANDIDATES)
    if not docs:
        return None

    best_doc: dict[str, Any] | None = None
    best_score = 0.0
    for doc in docs:
        score = _similarity_score(
            clean_description,
            str(doc.get("description") or ""),
            tokens,
        )
        if score > best_score:
            best_score = score
            best_doc = doc

    if not best_doc or best_score < MIN_HISTORY_SIMILARITY:
        return None

    category = best_doc.get("category") or None
    subcategory = best_doc.get("subcategory") or None
    if not category or not subcategory:
        return None

    return MatchResult(
        layer="past_transactions",
        category={
            "code": str(category.get("code") or ""),
            "name": str(category.get("name") or category.get("code") or ""),
        },
        subcategory={
            "code": str(subcategory.get("code") or ""),
            "name": str(subcategory.get("name") or subcategory.get("code") or ""),
        },
        score=best_score,
        metadata={
            "matched_description": best_doc.get("description"),
            "similarity": round(best_score, 3),
        },
    )


async def _match_merchant_rules(
    *,
    user_oid: ObjectId,
    keywords: list[str],
    clean_description: str,
    amount: float,
    mode: str,
    tx_type: str | None,
) -> MatchResult | None:
    if not keywords and not clean_description:
        return None

    base_query: dict[str, Any] = {
        "user_id": user_oid,
        "is_active": {"$ne": False},
    }
    if tx_type:
        base_query["type"] = tx_type

    query = {
        **base_query,
        "$or": [
            {"keyword": {"$in": keywords}},
            {"keyword": {"$regex": "|".join(re.escape(word) for word in keywords), "$options": "i"}} if keywords else {},
        ],
    }
    query["$or"] = [item for item in query["$or"] if item]
    if not query["$or"]:
        query.pop("$or")

    docs = await (
        db.merchant_rules.find(
            query,
            {
                "keyword": 1,
                "mode": 1,
                "min_amount": 1,
                "max_amount": 1,
                "category_code": 1,
                "category_name": 1,
                "subcategory_code": 1,
                "subcategory_name": 1,
                "priority": 1,
            },
        )
        .sort([("priority", -1), ("updated_at", -1)])
        .to_list(length=50)
    )
    if not docs:
        return None

    matched_docs = [
        doc
        for doc in docs
        if _keyword_matches(doc, keywords, clean_description)
        and _amount_matches(doc, amount)
        and _mode_matches(doc, mode)
    ]
    if not matched_docs:
        return None

    best_doc = matched_docs[0]
    category, subcategory = _category_pair(
        category_code=best_doc.get("category_code"),
        category_name=best_doc.get("category_name"),
        subcategory_code=best_doc.get("subcategory_code"),
        subcategory_name=best_doc.get("subcategory_name"),
    )
    if not category or not subcategory:
        return None

    return MatchResult(
        layer="merchant_rules",
        category=category,
        subcategory=subcategory,
        score=1.0,
        metadata={
            "matched_keyword": best_doc.get("keyword"),
            "priority": int(best_doc.get("priority") or 0),
        },
    )


async def _match_builtin_keywords(
    *,
    clean_description: str,
    keywords: list[str],
    tx_type: str | None,
) -> MatchResult | None:
    if tx_type and tx_type not in {"debit", "credit", "transfer"}:
        return None

    source = f"{clean_description} {' '.join(keywords)}".strip()
    if not source:
        return None

    normalized = _normalize_text(source)
    for rule in BUILTIN_KEYWORD_RULES:
        if tx_type and rule.get("type") and rule["type"] != tx_type:
            continue

        matched_keyword = next((kw for kw in _rule_keywords(rule) if _phrase_in_text(kw, normalized)), None)
        if not matched_keyword:
            continue

        category, subcategory = _category_pair(
            category_code=rule.get("category_code"),
            category_name=None,
            subcategory_code=rule.get("subcategory_code"),
            subcategory_name=None,
        )
        if not category or not subcategory:
            continue

        category, subcategory = await _resolve_category_pair(
            category_code=category.get("code"),
            subcategory_code=subcategory.get("code"),
            tx_type=tx_type,
        )
        if not category or not subcategory:
            continue

        return MatchResult(
            layer="builtin_keywords",
            category=category,
            subcategory=subcategory,
            score=0.65,
            metadata={"matched_keyword": matched_keyword},
        )

    return None


async def _user_name_parts(user_oid: ObjectId) -> set[str]:
    cache_key = str(user_oid)
    cached = _USER_NAME_PARTS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    user = await db.users.find_one(
        {"_id": user_oid},
        {"_id": 0, "username": 1, "full_name": 1, "email": 1},
    )
    if not user:
        _USER_NAME_PARTS_CACHE[cache_key] = set()
        return set()

    raw_parts: list[str] = []
    for value in [user.get("full_name"), user.get("username"), user.get("email")]:
        normalized = _normalize_text(value)
        if normalized:
            raw_parts.extend(TOKEN_RE.findall(normalized))

    parts = {
        token
        for token in raw_parts
        if len(token) >= 3 and token not in USER_NAME_STOPWORDS and not token.isdigit()
    }
    _USER_NAME_PARTS_CACHE[cache_key] = parts
    return parts


async def _match_self_transfer(
    *,
    user_oid: ObjectId,
    clean_description: str,
    tokens: list[str],
    tx_type: str | None,
) -> MatchResult | None:
    if not clean_description:
        return None

    name_parts = await _user_name_parts(user_oid)
    if not name_parts:
        return None

    source_tokens = set(_extract_tx_tokens(clean_description)) | set(tokens)
    matched_name_tokens = sorted(name_parts & source_tokens)
    if not matched_name_tokens:
        return None

    has_transfer_hint = any(_phrase_in_text(hint, clean_description) for hint in SELF_TRANSFER_HINTS)

    regex = "|".join(re.escape(token) for token in matched_name_tokens[:4])
    history_docs = await (
        db.transactions.find(
            {
                "user_id": user_oid,
                "deleted_at": None,
                "description": {"$regex": regex, "$options": "i"},
                "category.code": {"$exists": True, "$ne": None},
                "subcategory.code": {"$exists": True, "$ne": None},
            },
            {
                "type": 1,
                "description": 1,
                "category": 1,
                "subcategory": 1,
                "created_at": 1,
            },
        )
        .sort([("created_at", -1)])
        .limit(25)
        .to_list(length=25)
    )

    has_transfer_history = any(
        str(doc.get("type") or "").lower().startswith("transfer")
        or any(_phrase_in_text(hint, _normalize_text(doc.get("description"))) for hint in SELF_TRANSFER_HINTS)
        for doc in history_docs
    )

    if not has_transfer_hint and not has_transfer_history:
        return None

    default_pairs = {
        "transfer": ("transfer", "transfer"),
        "credit": ("other_income", "others"),
        "debit": ("others_expense", "miscellaneous"),
        None: ("others_expense", "miscellaneous"),
    }
    category_code, subcategory_code = default_pairs.get(tx_type, default_pairs[None])

    category, subcategory = await _resolve_category_pair(
        category_code=category_code,
        subcategory_code=subcategory_code,
        tx_type=tx_type,
    )
    if not category or not subcategory:
        return None

    return MatchResult(
        layer="self_transfer",
        category=category,
        subcategory=subcategory,
        score=0.6,
        metadata={
            "matched_name_tokens": matched_name_tokens,
            "transfer_hint": has_transfer_hint,
            "transfer_history": has_transfer_history,
        },
    )


def _assemble_confidence(
    *,
    memory_match: MatchResult | None,
    history_match: MatchResult | None,
    rule_match: MatchResult | None,
    mode: str,
) -> int:
    confidence = 0
    if memory_match:
        confidence += 40
    if history_match:
        confidence += 40
    if _normalize_text(mode) and _normalize_text(mode) != "unknown":
        confidence += 10
    if rule_match:
        confidence += 10
    return max(0, min(100, confidence))


def _coalesce_match(
    *,
    memory_match: MatchResult | None,
    history_match: MatchResult | None,
    rule_match: MatchResult | None,
) -> tuple[dict[str, str] | None, dict[str, str] | None, list[str]]:
    matched_layers: list[str] = []
    base_match = memory_match or history_match

    if memory_match:
        matched_layers.append(memory_match.layer)
    if history_match:
        matched_layers.append(history_match.layer)
    if rule_match:
        matched_layers.append(rule_match.layer)

    category = base_match.category if base_match else None
    subcategory = base_match.subcategory if base_match else None

    if rule_match:
        if not category:
            category = rule_match.category
        if rule_match.subcategory:
            if not category or not rule_match.category or rule_match.category.get("code") == category.get("code"):
                subcategory = rule_match.subcategory
                category = rule_match.category or category

    return category, subcategory, matched_layers


async def _categorize_payload(
    *,
    user_id: str | ObjectId,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Categorize a parsed narration payload.

    Returns:
        {
            "category": {"code": "...", "name": "..."} | None,
            "subcategory": {"code": "...", "name": "..."} | None,
            "confidence": 0-100,
            "needs_attention": bool,
            "matched_by": ["merchant_memory", "merchant_rules"],
            "explanations": {...},
        }
    """

    user_oid = _ensure_user_oid(user_id)

    clean_description = _normalize_text(payload.get("clean_description"))
    merchant = _normalize_text(payload.get("merchant"))
    tokens = _normalize_tokens(payload.get("tokens"))
    mode = _normalize_text(payload.get("mode")) or "unknown"
    tx_type = _normalize_text(payload.get("type")) or None
    amount = round_money(float(payload.get("amount") or 0))

    if not clean_description and not merchant and not tokens:
        raise ValidationError("Categorization requires a description, merchant, or tokens")
    if amount < 0:
        raise ValidationError("Amount cannot be negative")

    keywords = _candidate_keywords(
        {
            "merchant": merchant,
            "tokens": tokens,
            "clean_description": clean_description,
        }
    )

    memory_match = await _match_merchant_memory(
        user_oid=user_oid,
        keywords=keywords,
        tx_type=tx_type,
    )
    history_match = await _match_past_transactions(
        user_oid=user_oid,
        clean_description=clean_description,
        merchant=merchant,
        tokens=tokens,
        tx_type=tx_type,
    )
    rule_match = await _match_merchant_rules(
        user_oid=user_oid,
        keywords=keywords,
        clean_description=clean_description,
        amount=amount,
        mode=mode,
        tx_type=tx_type,
    )
    if not rule_match:
        rule_match = await _match_self_transfer(
            user_oid=user_oid,
            clean_description=clean_description,
            tokens=tokens,
            tx_type=tx_type,
        )
    if not rule_match:
        rule_match = await _match_builtin_keywords(
            clean_description=clean_description,
            keywords=keywords,
            tx_type=tx_type,
        )

    category, subcategory, matched_layers = _coalesce_match(
        memory_match=memory_match,
        history_match=history_match,
        rule_match=rule_match,
    )

    if category and subcategory and (not category.get("name") or not subcategory.get("name")):
        category, subcategory = await _resolve_category_pair(
            category_code=category.get("code"),
            subcategory_code=subcategory.get("code"),
            tx_type=tx_type,
        )

    confidence = _assemble_confidence(
        memory_match=memory_match,
        history_match=history_match,
        rule_match=rule_match,
        mode=mode,
    )

    return {
        "category": category,
        "subcategory": subcategory,
        "confidence": confidence,
        "needs_attention": confidence < 80 or not category or not subcategory,
        "matched_by": matched_layers,
        "explanations": {
            "merchant_memory": memory_match.metadata if memory_match else None,
            "past_transactions": history_match.metadata if history_match else None,
            "merchant_rules": rule_match.metadata if rule_match else None,
        },
    }


async def categorize_transaction(
    *,
    user_id: str | ObjectId,
    raw_description: str,
    amount: float,
    tx_type: str = "debit",
    mode: str | None = None,
) -> dict[str, Any]:
    """
    Single categorization entry point shared by UI, inbox, and Telegram.

    Returns normalized merchant/categorization metadata for the caller to use
    without duplicating any categorization rules.
    """

    cleaned_key = clean_memory_description(raw_description)
    narration = parse_narration(raw_description or "")
    merchant_key = await extract_merchant_key(
        user_id=user_id,
        cleaned_description=cleaned_key or str(narration.get("clean_description") or ""),
    )

    payload = {
        "clean_description": cleaned_key or narration.get("clean_description") or "",
        "merchant": merchant_key or narration.get("merchant") or "",
        "tokens": narration.get("tokens") or ([merchant_key] if merchant_key else []),
        "mode": mode or narration.get("mode") or "unknown",
        "amount": amount,
        "type": tx_type,
    }
    result = await _categorize_payload(user_id=user_id, payload=payload)
    confidence_ratio = _confidence_score_to_ratio(result.get("confidence") or 0)
    category = result.get("category") or {}
    subcategory = result.get("subcategory") or {}

    matched_layers = [str(layer) for layer in (result.get("matched_by") or [])]
    can_auto_learn = bool({"past_transactions", "merchant_rules", "builtin_keywords"} & set(matched_layers))
    safe_merchant_key = _normalize_text(merchant_key)
    if (
        can_auto_learn
        and safe_merchant_key
        and len(safe_merchant_key) >= 3
        and safe_merchant_key not in AUTO_LEARN_STOPWORDS
        and not safe_merchant_key.isdigit()
        and category.get("code")
        and subcategory.get("code")
    ):
        try:
            await learn_merchant_memory(
                user_id=user_id,
                cleaned_key=safe_merchant_key,
                merchant_name=safe_merchant_key.title(),
                category=str(category.get("name") or category.get("code") or ""),
                subcategory=str(subcategory.get("name") or subcategory.get("code") or ""),
                category_code=str(category.get("code") or "") or None,
                subcategory_code=str(subcategory.get("code") or "") or None,
                confidence=max(0.5, confidence_ratio),
                learned_from="auto",
            )
        except Exception:
            logger.exception("merchant memory auto-learn failed for key=%s", safe_merchant_key)
    elif (
        safe_merchant_key
        and len(safe_merchant_key) >= 2
        and safe_merchant_key not in AUTO_LEARN_STOPWORDS
        and not safe_merchant_key.isdigit()
        and not category.get("code")
    ):
        # Auto-append unknown merchants for admin categorization
        try:
            await learn_merchant_memory(
                user_id=user_id,
                cleaned_key=safe_merchant_key,
                merchant_name=safe_merchant_key.title(),
                category="Uncategorized",
                subcategory="Uncategorized",
                category_code=None,
                subcategory_code=None,
                confidence=0.0,
                learned_from="auto_detected",
            )
        except Exception:
            logger.debug("merchant memory auto-append failed for key=%s", safe_merchant_key)

    return {
        **result,
        "raw_description": raw_description,
        "cleaned_key": cleaned_key or merchant_key or "",
        "detected_merchant": merchant_key.title() if merchant_key else None,
        "suggested_category": category.get("name"),
        "suggested_category_code": category.get("code"),
        "suggested_subcategory": subcategory.get("name"),
        "suggested_subcategory_code": subcategory.get("code"),
        "confidence_ratio": confidence_ratio,
        "confidence_percent": int(round(confidence_ratio * 100)),
        "needs_attention": confidence_ratio < 0.85 or not category or not subcategory,
    }


def _confidence_score_to_ratio(value: int | float) -> float:
    score = float(value or 0)
    if score > 1:
        score = score / 100.0
    return max(0.0, min(1.0, score))


async def learn_from_override(
    *,
    user_id: str | ObjectId,
    raw_description: str,
    category: dict[str, str],
    subcategory: dict[str, str],
    merchant_name: str | None = None,
) -> None:
    cleaned_key = clean_memory_description(raw_description)
    merchant_key = await extract_merchant_key(
        user_id=user_id,
        cleaned_description=cleaned_key,
    )
    effective_key = merchant_key or cleaned_key
    if not effective_key:
        return
    await learn_merchant_memory(
        user_id=user_id,
        cleaned_key=effective_key,
        merchant_name=merchant_name or effective_key.title(),
        category=str(category.get("name") or category.get("code") or ""),
        subcategory=str(subcategory.get("name") or subcategory.get("code") or ""),
        category_code=str(category.get("code") or "") or None,
        subcategory_code=str(subcategory.get("code") or "") or None,
        learned_from="user",
    )


__all__ = ["categorize_transaction", "learn_from_override"]
