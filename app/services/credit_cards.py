"""
Credit card domain service.

This module owns:
- credit card master records
- card transactions
- bill estimation and bill snapshot generation
- bill payments and utilization
- EMI schedule generation
- due alerts and background sweep helpers
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from bson import ObjectId

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.mongo import db
from app.helpers.money import round_money
from app.services.audit import audit_log

UTC = timezone.utc

COL_CARDS = "credit_cards"
COL_TXNS = "credit_card_transactions"
COL_BILLS = "credit_card_bills"
COL_BILL_ITEMS = "credit_card_bill_items"
COL_PAYMENTS = "credit_card_payments"
COL_EMIS = "credit_card_emis"
COL_EMI_SCHEDULE = "credit_card_emi_schedule"
COL_ALERTS = "credit_alerts"

AUTO_CATEGORY_RULES = {
    "amazon": "shopping",
    "flipkart": "shopping",
    "swiggy": "food",
    "zomato": "food",
    "uber": "transport",
    "ola": "transport",
    "netflix": "subscriptions",
    "spotify": "subscriptions",
    "apollo": "health",
    "airtel": "utilities",
    "jio": "utilities",
}


@dataclass
class BillingCycle:
    cycle_key: str
    start: datetime
    end: datetime
    statement_date: datetime
    due_date: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _to_object_id(value: str | ObjectId, *, label: str) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(value):
        raise ValidationError(f"Invalid {label}")
    return ObjectId(value)


def _normalize_amount(value: float | Decimal | int | None) -> float:
    return round_money(float(value or 0))


def _to_utc(value: datetime | date | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _end_of_day(value: datetime) -> datetime:
    return value.replace(hour=23, minute=59, second=59, microsecond=999999)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - timedelta(days=1)).day


def _safe_day(year: int, month: int, day: int) -> int:
    return min(max(1, day), _days_in_month(year, month))


def _cycle_key(value: datetime) -> str:
    return value.strftime("%Y-%m")


def _infer_category(merchant: str | None, description: str | None, explicit: str | None) -> str:
    if explicit:
        return explicit.strip().lower()
    haystack = f"{merchant or ''} {description or ''}".lower()
    for token, category in AUTO_CATEGORY_RULES.items():
        if token in haystack:
            return category
    return "uncategorized"


def _get_billing_cycle(card: dict[str, Any], anchor: datetime | None = None) -> BillingCycle:
    anchor = anchor or _now()
    start_day = int(card.get("billing_cycle_start_day") or 1)
    end_day = int(card.get("billing_cycle_end_day") or 30)
    due_day = int(card.get("due_day") or 5)

    year = anchor.year
    month = anchor.month
    if anchor.day < start_day:
        month -= 1
        if month == 0:
            year -= 1
            month = 12

    start_dt = datetime(year, month, _safe_day(year, month, start_day), tzinfo=UTC)
    end_dt = datetime(year, month, _safe_day(year, month, end_day), tzinfo=UTC)
    end_dt = _end_of_day(end_dt)

    next_month_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    statement_date = datetime(next_month_year, next_month, 1, tzinfo=UTC)
    due_date = datetime(next_month_year, next_month, _safe_day(next_month_year, next_month, due_day), tzinfo=UTC)

    return BillingCycle(
        cycle_key=_cycle_key(end_dt),
        start=start_dt,
        end=end_dt,
        statement_date=statement_date,
        due_date=due_date,
    )


def _signed_transaction_amount(txn: dict[str, Any]) -> float:
    positive_types = {"purchase", "fee", "late_fee", "interest", "gst", "bill_adjustment", "emi_component"}
    negative_types = {"refund", "reversal", "payment"}
    amount = _normalize_amount(txn.get("amount"))
    txn_type = str(txn.get("txn_type") or "purchase")
    if txn_type in negative_types:
        return -amount
    if txn_type in positive_types:
        return amount
    return amount


def calculate_minimum_due(*, final_amount: float, emi_due: float = 0.0, finance_charges: float = 0.0, flat_minimum: float = 200.0, percent: float = 0.05) -> float:
    percent_due = _normalize_amount(final_amount * percent)
    return _normalize_amount(max(percent_due, emi_due + finance_charges, flat_minimum if final_amount > 0 else 0.0))


def calculate_emi_amount(*, principal: float, annual_rate: float, tenure_months: int, gst_rate: float = 18.0) -> float:
    principal = _normalize_amount(principal)
    if tenure_months <= 0:
        raise ValidationError("EMI tenure must be positive")
    monthly_rate = float(annual_rate or 0.0) / 12 / 100
    if monthly_rate == 0:
        return _normalize_amount(principal / tenure_months)
    factor = (1 + monthly_rate) ** tenure_months
    emi = principal * monthly_rate * factor / (factor - 1)
    return _normalize_amount(emi)


def calculate_emi_breakdown(*, opening_principal: float, annual_rate: float, gst_rate: float, emi_amount: float) -> dict[str, float]:
    opening_principal = _normalize_amount(opening_principal)
    monthly_rate = float(annual_rate or 0.0) / 12 / 100
    interest = _normalize_amount(opening_principal * monthly_rate)
    gst = _normalize_amount(interest * float(gst_rate or 0.0) / 100)
    principal_component = _normalize_amount(max(float(emi_amount) - interest - gst, 0.0))
    closing_principal = _normalize_amount(max(opening_principal - principal_component, 0.0))
    return {
        "principal": principal_component,
        "interest": interest,
        "gst": gst,
        "closing_principal": closing_principal,
    }


def _serialize(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            out[key] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, list):
            out[key] = [str(v) if isinstance(v, ObjectId) else v for v in value]
        else:
            out[key] = value
    if "_id" in doc:
        out["id"] = str(doc["_id"])
    return out


def _day_from_datetime(value: datetime | None, default: int) -> int:
    if not value:
        return default
    return max(1, min(int(value.day), 31))


async def sync_credit_card_account_record(*, user_id: str, account_id: str) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    account_oid = _to_object_id(account_id, label="account")
    account = await db.accounts.find_one({"_id": account_oid, "user_id": user_oid, "deleted_at": None})
    if not account:
        raise NotFoundError("Credit card account not found")
    if account.get("type") != "credit_card":
        raise ValidationError("Only credit card accounts can be synced")

    now = _now()
    total_limit = _normalize_amount(account.get("credit_limit"))
    raw_balance = float(account.get("balance") or 0.0)
    outstanding = _normalize_amount(abs(raw_balance) if raw_balance < 0 else 0.0)
    available_limit = _normalize_amount(max(total_limit - outstanding, 0.0))
    bill_generation_date = _to_utc(account.get("bill_generation_date"))
    payment_due_date = _to_utc(account.get("payment_due_date"))

    updates = {
        "card_name": (account.get("name") or account.get("bank_name") or "Credit Card").strip(),
        "bank_name": (account.get("bank_name") or "").strip() or None,
        "network": (account.get("card_network") or "visa").strip().lower(),
        "total_limit": total_limit,
        "available_limit": available_limit,
        "billing_cycle_start_day": int(account.get("billing_cycle_start_day") or 1),
        "billing_cycle_end_day": int(account.get("billing_cycle_end_day") or _day_from_datetime(bill_generation_date, 30)),
        "due_day": int(account.get("due_day") or _day_from_datetime(payment_due_date, 5)),
        "statement_generation_mode": "manual",
        "status": "active",
        "source_account_id": account_oid,
        "updated_at": now,
        "deleted_at": None,
    }

    existing = await db[COL_CARDS].find_one({"user_id": user_oid, "source_account_id": account_oid})
    if existing:
        await db[COL_CARDS].update_one({"_id": existing["_id"]}, {"$set": updates, "$setOnInsert": {"created_at": now}})
        synced = await db[COL_CARDS].find_one({"_id": existing["_id"]})
        return _serialize(synced)

    doc = {
        "user_id": user_oid,
        **updates,
        "last4": None,
        "created_at": now,
    }
    result = await db[COL_CARDS].insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


async def archive_credit_card_account_record(*, user_id: str, account_id: str) -> None:
    user_oid = _to_object_id(user_id, label="user")
    account_oid = _to_object_id(account_id, label="account")
    await db[COL_CARDS].update_many(
        {"user_id": user_oid, "source_account_id": account_oid, "deleted_at": None},
        {"$set": {"deleted_at": _now(), "updated_at": _now(), "status": "closed"}},
    )


async def generate_bill_snapshot_for_account(*, user_id: str, account_id: str, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    account_oid = _to_object_id(account_id, label="account")
    card = await db[COL_CARDS].find_one({"user_id": user_oid, "source_account_id": account_oid, "deleted_at": None})
    if not card:
        synced = await sync_credit_card_account_record(user_id=user_id, account_id=account_id)
        card_id = synced["id"]
    else:
        card_id = str(card["_id"])
    return await generate_bill_snapshot(user_id=user_id, card_id=card_id, request=request)


async def create_credit_card(*, user_id: str, payload: Any, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    existing = await db[COL_CARDS].find_one({
        "user_id": user_oid,
        "card_name": payload.card_name.strip(),
        "deleted_at": None,
    })
    if existing:
        raise ConflictError("Credit card with this name already exists")

    now = _now()
    total_limit = _normalize_amount(payload.total_limit)
    doc = {
        "user_id": user_oid,
        "card_name": payload.card_name.strip(),
        "bank_name": (payload.bank_name or "").strip() or None,
        "network": (payload.network or "visa").strip().lower(),
        "last4": (payload.last4 or "").strip() or None,
        "total_limit": total_limit,
        "available_limit": total_limit,
        "billing_cycle_start_day": int(payload.billing_cycle_start_day),
        "billing_cycle_end_day": int(payload.billing_cycle_end_day),
        "due_day": int(payload.due_day),
        "statement_generation_mode": (payload.statement_generation_mode or "auto").strip().lower(),
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    result = await db[COL_CARDS].insert_one(doc)
    doc["_id"] = result.inserted_id
    await audit_log(action="CREDIT_CARD_CREATED", request=request, user={"user_id": user_id}, meta={"card_id": str(result.inserted_id), "card_name": doc["card_name"], "limit": total_limit})
    return _serialize(doc)


async def list_credit_cards(*, user_id: str) -> list[dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    cards = await db[COL_CARDS].find({"user_id": user_oid, "deleted_at": None}).sort("created_at", 1).to_list(length=200)
    return [_serialize(card) for card in cards]


async def get_credit_card(*, user_id: str, card_id: str) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    card = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not card:
        raise NotFoundError("Credit card not found")
    return _serialize(card)


async def update_credit_card(*, user_id: str, card_id: str, payload: Any, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    existing = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not existing:
        raise NotFoundError("Credit card not found")

    updates = {"updated_at": _now()}
    for field in ["card_name", "bank_name", "network", "statement_generation_mode", "status", "last4"]:
        value = getattr(payload, field, None)
        if value is not None:
            updates[field] = value.strip().lower() if field == "network" else value.strip() if isinstance(value, str) else value
    for field in ["billing_cycle_start_day", "billing_cycle_end_day", "due_day"]:
        value = getattr(payload, field, None)
        if value is not None:
            updates[field] = int(value)
    if getattr(payload, "total_limit", None) is not None:
        updates["total_limit"] = _normalize_amount(payload.total_limit)

    await db[COL_CARDS].update_one({"_id": card_oid}, {"$set": updates})
    await audit_log(action="CREDIT_CARD_UPDATED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "fields": sorted(k for k in updates.keys() if k != "updated_at")})
    card = await db[COL_CARDS].find_one({"_id": card_oid})
    return _serialize(card)


async def delete_credit_card(*, user_id: str, card_id: str, request=None) -> None:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    card = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not card:
        raise NotFoundError("Credit card not found")
    await db[COL_CARDS].update_one({"_id": card_oid}, {"$set": {"deleted_at": _now(), "status": "closed", "updated_at": _now()}})
    await audit_log(action="CREDIT_CARD_DELETED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "card_name": card.get("card_name")})


async def add_credit_card_transaction(*, user_id: str, card_id: str, payload: Any, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    card = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not card:
        raise NotFoundError("Credit card not found")

    txn_date = _to_utc(payload.txn_date)
    cycle = _get_billing_cycle(card, txn_date or _now())
    amount = _normalize_amount(payload.amount)
    category = _infer_category(payload.merchant, payload.description, payload.category)
    now = _now()
    doc = {
        "user_id": user_oid,
        "card_id": card_oid,
        "bill_id": None,
        "txn_type": payload.txn_type,
        "amount": amount,
        "txn_date": txn_date,
        "posted_date": _to_utc(payload.posted_date) or txn_date,
        "merchant": (payload.merchant or "").strip() or None,
        "category": category,
        "description": (payload.description or "").strip() or None,
        "source": (payload.source or "manual").strip().lower(),
        "status": (payload.status or "posted").strip().lower(),
        "is_emi": bool(payload.is_emi),
        "emi_details": payload.emi_details or None,
        "emi_id": None,
        "bill_cycle_key": cycle.cycle_key,
        "frozen_in_bill": False,
        "meta": {},
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    result = await db[COL_TXNS].insert_one(doc)
    doc["_id"] = result.inserted_id

    if doc["is_emi"] and payload.emi_details:
        emi_payload = type("EmiPayload", (), payload.emi_details | {"source_transaction_id": str(result.inserted_id)})
        try:
            emi = await create_emi_plan(user_id=user_id, card_id=card_id, payload=emi_payload, request=request)
            await db[COL_TXNS].update_one({"_id": result.inserted_id}, {"$set": {"emi_id": _to_object_id(emi["id"], label="emi")}})
        except Exception:
            pass

    await audit_log(action="CREDIT_CARD_TXN_CREATED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "txn_id": str(result.inserted_id), "amount": amount, "type": payload.txn_type})
    return _serialize(doc)


async def list_credit_card_transactions(*, user_id: str, card_id: str, limit: int = 200) -> list[dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    txns = await db[COL_TXNS].find({"user_id": user_oid, "card_id": card_oid, "deleted_at": None}).sort("txn_date", -1).to_list(length=limit)
    return [_serialize(txn) for txn in txns]


async def get_credit_card_transaction(*, user_id: str, card_id: str, txn_id: str) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    txn_oid = _to_object_id(txn_id, label="transaction")
    txn = await db[COL_TXNS].find_one({"_id": txn_oid, "user_id": user_oid, "card_id": card_oid, "deleted_at": None})
    if not txn:
        raise NotFoundError("Credit card transaction not found")
    return _serialize(txn)


async def update_credit_card_transaction(*, user_id: str, card_id: str, txn_id: str, payload: Any, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    txn_oid = _to_object_id(txn_id, label="transaction")

    card = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not card:
        raise NotFoundError("Credit card not found")

    txn = await db[COL_TXNS].find_one({"_id": txn_oid, "user_id": user_oid, "card_id": card_oid, "deleted_at": None})
    if not txn:
        raise NotFoundError("Credit card transaction not found")
    if txn.get("frozen_in_bill"):
        raise ValidationError("Frozen billed transactions cannot be edited. Add a bill adjustment instead.")

    updates = {"updated_at": _now()}

    txn_date = _to_utc(getattr(payload, "txn_date", None))
    posted_date = _to_utc(getattr(payload, "posted_date", None))
    if txn_date is not None:
        updates["txn_date"] = txn_date
    if posted_date is not None:
        updates["posted_date"] = posted_date

    if getattr(payload, "txn_type", None) is not None:
        updates["txn_type"] = payload.txn_type
    if getattr(payload, "amount", None) is not None:
        updates["amount"] = _normalize_amount(payload.amount)
    if getattr(payload, "merchant", None) is not None:
        updates["merchant"] = (payload.merchant or "").strip() or None
    if getattr(payload, "description", None) is not None:
        updates["description"] = (payload.description or "").strip() or None
    if getattr(payload, "source", None) is not None:
        updates["source"] = (payload.source or "manual").strip().lower()
    if getattr(payload, "status", None) is not None:
        updates["status"] = (payload.status or "posted").strip().lower()
    if getattr(payload, "is_emi", None) is not None:
        updates["is_emi"] = bool(payload.is_emi)
    if getattr(payload, "emi_details", None) is not None:
        updates["emi_details"] = payload.emi_details or None

    explicit_category = getattr(payload, "category", None)
    if explicit_category is not None:
        updates["category"] = _infer_category(
            updates.get("merchant", txn.get("merchant")),
            updates.get("description", txn.get("description")),
            explicit_category,
        )
    elif any(key in updates for key in ("merchant", "description")):
        updates["category"] = _infer_category(
            updates.get("merchant", txn.get("merchant")),
            updates.get("description", txn.get("description")),
            txn.get("category"),
        )

    if "txn_date" in updates:
        cycle = _get_billing_cycle(card, updates["txn_date"])
        updates["bill_cycle_key"] = cycle.cycle_key
        if "posted_date" not in updates and txn.get("posted_date") is None:
            updates["posted_date"] = updates["txn_date"]

    await db[COL_TXNS].update_one({"_id": txn_oid}, {"$set": updates})
    await audit_log(
        action="CREDIT_CARD_TXN_UPDATED",
        request=request,
        user={"user_id": user_id},
        meta={"card_id": card_id, "txn_id": txn_id, "fields": sorted(k for k in updates.keys() if k != "updated_at")},
    )
    updated = await db[COL_TXNS].find_one({"_id": txn_oid})
    return _serialize(updated)


async def delete_credit_card_transaction(*, user_id: str, card_id: str, txn_id: str, request=None) -> None:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    txn_oid = _to_object_id(txn_id, label="transaction")
    txn = await db[COL_TXNS].find_one({"_id": txn_oid, "user_id": user_oid, "card_id": card_oid, "deleted_at": None})
    if not txn:
        raise NotFoundError("Credit card transaction not found")
    if txn.get("frozen_in_bill"):
        raise ValidationError("Frozen billed transactions cannot be deleted. Add a bill adjustment instead.")

    await db[COL_TXNS].update_one({"_id": txn_oid}, {"$set": {"deleted_at": _now(), "updated_at": _now()}})
    await audit_log(
        action="CREDIT_CARD_TXN_DELETED",
        request=request,
        user={"user_id": user_id},
        meta={"card_id": card_id, "txn_id": txn_id, "amount": _normalize_amount(txn.get("amount")), "txn_type": txn.get("txn_type")},
    )


async def _get_billable_transactions(*, user_oid: ObjectId, card_oid: ObjectId, cycle: BillingCycle) -> list[dict[str, Any]]:
    return await db[COL_TXNS].find({
        "user_id": user_oid,
        "card_id": card_oid,
        "deleted_at": None,
        "txn_date": {"$gte": cycle.start, "$lte": cycle.end},
    }).sort("txn_date", 1).to_list(length=2000)


async def _get_cycle_emi_components(*, user_oid: ObjectId, card_oid: ObjectId, cycle: BillingCycle) -> list[dict[str, Any]]:
    return await db[COL_EMI_SCHEDULE].find({
        "user_id": user_oid,
        "card_id": card_oid,
        "bill_cycle_key": cycle.cycle_key,
        "status": {"$in": ["pending", "projected"]},
    }).sort("installment_no", 1).to_list(length=200)


async def calculate_estimated_bill(*, user_id: str, card_id: str) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    card = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not card:
        raise NotFoundError("Credit card not found")

    cycle = _get_billing_cycle(card)
    txns = await _get_billable_transactions(user_oid=user_oid, card_oid=card_oid, cycle=cycle)
    emi_rows = await _get_cycle_emi_components(user_oid=user_oid, card_oid=card_oid, cycle=cycle)

    purchase_total = _normalize_amount(sum(_signed_transaction_amount(txn) for txn in txns))
    emi_total = _normalize_amount(sum(_normalize_amount(item.get("emi_amount")) for item in emi_rows))
    estimated = _normalize_amount(purchase_total + emi_total)
    min_due = calculate_minimum_due(final_amount=estimated, emi_due=emi_total)

    return {
        "card": _serialize(card),
        "cycle_key": cycle.cycle_key,
        "cycle_start": cycle.start.isoformat(),
        "cycle_end": cycle.end.isoformat(),
        "statement_date": cycle.statement_date.isoformat(),
        "due_date": cycle.due_date.isoformat(),
        "estimated_amount": estimated,
        "minimum_due": min_due,
        "transaction_count": len(txns),
        "emi_component_count": len(emi_rows),
        "purchase_total": purchase_total,
        "emi_total": emi_total,
        "transactions": [_serialize(txn) for txn in txns],
        "emi_components": [_serialize(item) for item in emi_rows],
    }


async def generate_bill_snapshot(*, user_id: str, card_id: str, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    card = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not card:
        raise NotFoundError("Credit card not found")

    cycle = _get_billing_cycle(card)
    existing = await db[COL_BILLS].find_one({"user_id": user_oid, "card_id": card_oid, "cycle_key": cycle.cycle_key})
    if existing:
        return _serialize(existing)

    estimate = await calculate_estimated_bill(user_id=user_id, card_id=card_id)
    estimated_amount = _normalize_amount(estimate["estimated_amount"])
    minimum_due = _normalize_amount(estimate["minimum_due"])
    now = _now()
    bill_doc = {
        "user_id": user_oid,
        "card_id": card_oid,
        "cycle_key": cycle.cycle_key,
        "cycle_start": cycle.start,
        "cycle_end": cycle.end,
        "statement_date": cycle.statement_date,
        "due_date": cycle.due_date,
        "estimated_amount": estimated_amount,
        "final_amount": estimated_amount,
        "adjustment_amount": 0.0,
        "minimum_due": minimum_due,
        "paid_amount": 0.0,
        "outstanding_amount": estimated_amount,
        "payment_status": "unpaid",
        "late_fee_applied": False,
        "interest_applied": False,
        "status": "generated",
        "snapshot": {
            "txn_count": int(estimate["transaction_count"]),
            "purchase_total": _normalize_amount(estimate["purchase_total"]),
            "refund_total": 0.0,
            "emi_total": _normalize_amount(estimate["emi_total"]),
            "fees_total": 0.0,
            "interest_total": 0.0,
            "gst_total": 0.0,
        },
        "generated_at": now,
        "created_at": now,
        "updated_at": now,
    }
    result = await db[COL_BILLS].insert_one(bill_doc)
    bill_doc["_id"] = result.inserted_id

    bill_items: list[dict[str, Any]] = []
    for txn in estimate["transactions"]:
        bill_items.append({
            "user_id": user_oid,
            "bill_id": result.inserted_id,
            "card_id": card_oid,
            "source_transaction_id": _to_object_id(txn["id"], label="transaction"),
            "item_type": txn.get("txn_type") or "purchase",
            "label": txn.get("description") or txn.get("merchant") or "Card transaction",
            "txn_date": _to_utc(datetime.fromisoformat(txn["txn_date"])),
            "amount": _normalize_amount(txn.get("amount")),
            "category": txn.get("category"),
            "is_emi_component": False,
            "emi_breakdown": None,
            "created_at": now,
        })
    for component in estimate["emi_components"]:
        bill_items.append({
            "user_id": user_oid,
            "bill_id": result.inserted_id,
            "card_id": card_oid,
            "source_transaction_id": None,
            "item_type": "emi_component",
            "label": f"EMI installment {component.get('installment_no')}",
            "txn_date": _to_utc(datetime.fromisoformat(component["due_date"])),
            "amount": _normalize_amount(component.get("emi_amount")),
            "category": "emi",
            "is_emi_component": True,
            "emi_breakdown": {
                "principal": _normalize_amount(component.get("principal_component")),
                "interest": _normalize_amount(component.get("interest_component")),
                "gst_on_interest": _normalize_amount(component.get("gst_component")),
            },
            "created_at": now,
        })
    if bill_items:
        await db[COL_BILL_ITEMS].insert_many(bill_items)

    await db[COL_TXNS].update_many({
        "user_id": user_oid,
        "card_id": card_oid,
        "deleted_at": None,
        "txn_date": {"$gte": cycle.start, "$lte": cycle.end},
    }, {"$set": {"bill_id": result.inserted_id, "frozen_in_bill": True, "updated_at": now}})

    await schedule_bill_alerts(user_id=user_id, bill_id=str(result.inserted_id), bill_doc=bill_doc)
    await audit_log(action="CREDIT_CARD_BILL_GENERATED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "bill_id": str(result.inserted_id), "cycle_key": cycle.cycle_key, "estimated_amount": estimated_amount})
    return _serialize(bill_doc)


async def list_bills(*, user_id: str, card_id: str) -> list[dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    bills = await db[COL_BILLS].find({"user_id": user_oid, "card_id": card_oid}).sort("statement_date", -1).to_list(length=120)
    return [_serialize(bill) for bill in bills]


async def get_bill(*, user_id: str, card_id: str, bill_id: str) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    bill_oid = _to_object_id(bill_id, label="bill")
    bill = await db[COL_BILLS].find_one({"_id": bill_oid, "user_id": user_oid, "card_id": card_oid})
    if not bill:
        raise NotFoundError("Bill not found")
    items = await db[COL_BILL_ITEMS].find({"bill_id": bill_oid}).sort("txn_date", 1).to_list(length=2000)
    payload = _serialize(bill)
    payload["items"] = [_serialize(item) for item in items]
    return payload


async def update_bill(*, user_id: str, card_id: str, bill_id: str, payload: Any, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    bill_oid = _to_object_id(bill_id, label="bill")
    bill = await db[COL_BILLS].find_one({"_id": bill_oid, "user_id": user_oid, "card_id": card_oid})
    if not bill:
        raise NotFoundError("Bill not found")

    updates = {"updated_at": _now()}
    final_amount = _normalize_amount(payload.final_amount) if payload.final_amount is not None else _normalize_amount(bill.get("final_amount"))
    if payload.final_amount is not None:
        adjustment = _normalize_amount(final_amount - _normalize_amount(bill.get("estimated_amount")))
        updates["final_amount"] = final_amount
        updates["adjustment_amount"] = adjustment
        updates["outstanding_amount"] = _normalize_amount(final_amount - _normalize_amount(bill.get("paid_amount")))
        if adjustment != 0:
            await db[COL_TXNS].insert_one({
                "user_id": user_oid,
                "card_id": card_oid,
                "bill_id": bill_oid,
                "txn_type": "bill_adjustment",
                "amount": adjustment,
                "txn_date": _now(),
                "posted_date": _now(),
                "merchant": None,
                "category": "bill_adjustment",
                "description": payload.note or "Statement correction adjustment",
                "source": "system",
                "status": "posted",
                "is_emi": False,
                "emi_details": None,
                "emi_id": None,
                "bill_cycle_key": bill.get("cycle_key"),
                "frozen_in_bill": True,
                "meta": {"bill_id": bill_id},
                "created_at": _now(),
                "updated_at": _now(),
                "deleted_at": None,
            })
    if payload.minimum_due is not None:
        updates["minimum_due"] = _normalize_amount(payload.minimum_due)
    elif payload.final_amount is not None:
        updates["minimum_due"] = calculate_minimum_due(final_amount=final_amount)
    if payload.note is not None:
        updates["note"] = payload.note.strip()

    await db[COL_BILLS].update_one({"_id": bill_oid}, {"$set": updates})
    await audit_log(action="CREDIT_CARD_BILL_UPDATED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "bill_id": bill_id, "fields": sorted(k for k in updates.keys() if k != "updated_at")})
    updated = await db[COL_BILLS].find_one({"_id": bill_oid})
    return _serialize(updated)


async def record_bill_payment(*, user_id: str, card_id: str, bill_id: str, payload: Any, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    bill_oid = _to_object_id(bill_id, label="bill")
    bill = await db[COL_BILLS].find_one({"_id": bill_oid, "user_id": user_oid, "card_id": card_oid})
    if not bill:
        raise NotFoundError("Bill not found")

    amount = _normalize_amount(payload.amount)
    if amount <= 0:
        raise ValidationError("Payment amount must be positive")
    payment_date = _to_utc(payload.payment_date) or _now()
    payment_doc = {
        "user_id": user_oid,
        "card_id": card_oid,
        "bill_id": bill_oid,
        "source_account_id": _to_object_id(payload.source_account_id, label="source account") if payload.source_account_id else None,
        "amount": amount,
        "payment_date": payment_date,
        "payment_mode": (payload.payment_mode or "bank_transfer").strip().lower(),
        "reference_no": (payload.reference_no or "").strip() or None,
        "status": "success",
        "created_at": _now(),
    }
    result = await db[COL_PAYMENTS].insert_one(payment_doc)
    await db[COL_TXNS].insert_one({
        "user_id": user_oid,
        "card_id": card_oid,
        "bill_id": bill_oid,
        "txn_type": "payment",
        "amount": amount,
        "txn_date": payment_date,
        "posted_date": payment_date,
        "merchant": None,
        "category": "payment",
        "description": "Credit card bill payment",
        "source": "system",
        "status": "posted",
        "is_emi": False,
        "emi_details": None,
        "emi_id": None,
        "bill_cycle_key": bill.get("cycle_key"),
        "frozen_in_bill": True,
        "meta": {"payment_id": str(result.inserted_id)},
        "created_at": _now(),
        "updated_at": _now(),
        "deleted_at": None,
    })

    new_paid = _normalize_amount(_normalize_amount(bill.get("paid_amount")) + amount)
    outstanding = _normalize_amount(max(_normalize_amount(bill.get("final_amount")) - new_paid, 0.0))
    status = "paid" if outstanding == 0 else "partial"
    await db[COL_BILLS].update_one({"_id": bill_oid}, {"$set": {"paid_amount": new_paid, "outstanding_amount": outstanding, "payment_status": status, "updated_at": _now()}})
    if status == "paid":
        await db[COL_ALERTS].update_many({"bill_id": bill_oid, "status": {"$in": ["pending", "scheduled"]}}, {"$set": {"status": "cancelled", "updated_at": _now()}})
    await audit_log(action="CREDIT_CARD_BILL_PAYMENT_RECORDED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "bill_id": bill_id, "amount": amount, "payment_status": status})
    updated = await db[COL_BILLS].find_one({"_id": bill_oid})
    return _serialize(updated)


async def list_payments(*, user_id: str, card_id: str) -> list[dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    rows = await db[COL_PAYMENTS].find({"user_id": user_oid, "card_id": card_oid}).sort("payment_date", -1).to_list(length=200)
    return [_serialize(row) for row in rows]


async def calculate_card_outstanding(*, user_id: str, card_id: str) -> float:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    txns = await db[COL_TXNS].find({"user_id": user_oid, "card_id": card_oid, "deleted_at": None}).to_list(length=5000)
    return _normalize_amount(sum(_signed_transaction_amount(txn) for txn in txns))


async def calculate_card_utilization(*, user_id: str, card_id: str) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    card = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not card:
        raise NotFoundError("Credit card not found")
    outstanding = await calculate_card_outstanding(user_id=user_id, card_id=card_id)
    total_limit = _normalize_amount(card.get("total_limit"))
    utilization = _normalize_amount((outstanding / total_limit) * 100 if total_limit else 0.0)
    available_limit = _normalize_amount(max(total_limit - outstanding, 0.0))
    await db[COL_CARDS].update_one({"_id": card_oid}, {"$set": {"available_limit": available_limit, "updated_at": _now()}})
    return {
        "card_id": card_id,
        "total_limit": total_limit,
        "outstanding": outstanding,
        "available_limit": available_limit,
        "utilization_percent": utilization,
    }


async def create_emi_plan(*, user_id: str, card_id: str, payload: Any, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    card = await db[COL_CARDS].find_one({"_id": card_oid, "user_id": user_oid, "deleted_at": None})
    if not card:
        raise NotFoundError("Credit card not found")

    principal = _normalize_amount(getattr(payload, "principal", None) or getattr(payload, "total_amount", None))
    annual_rate = float(getattr(payload, "interest_rate_annual", None) or getattr(payload, "interest_rate", 0) or 0)
    tenure_months = int(getattr(payload, "tenure_months", None) or getattr(payload, "total_installments", 0) or 0)
    start_date = _to_utc(getattr(payload, "start_date", None) or getattr(payload, "next_due_date", None) or _now())
    gst_rate = float(getattr(payload, "gst_rate", 18.0) or 18.0)
    schedule_type = getattr(payload, "schedule_type", "reducing") or "reducing"
    if principal <= 0 or tenure_months <= 0:
        raise ValidationError("EMI principal and tenure are required")

    emi_amount = calculate_emi_amount(principal=principal, annual_rate=annual_rate, tenure_months=tenure_months, gst_rate=gst_rate)
    now = _now()
    doc = {
        "user_id": user_oid,
        "card_id": card_oid,
        "account_id": card_oid,
        "source_transaction_id": _to_object_id(getattr(payload, "source_transaction_id", None), label="source transaction") if getattr(payload, "source_transaction_id", None) else None,
        "title": getattr(payload, "title", "EMI").strip(),
        "principal": principal,
        "interest_rate_annual": annual_rate,
        "gst_rate": gst_rate,
        "tenure_months": tenure_months,
        "emi_amount": emi_amount,
        "start_date": start_date,
        "next_bill_date": start_date,
        "months_paid": 0,
        "months_remaining": tenure_months,
        "principal_outstanding": principal,
        "status": "active",
        "schedule_type": schedule_type,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    result = await db[COL_EMIS].insert_one(doc)
    doc["_id"] = result.inserted_id
    schedule_rows = await build_emi_schedule(user_id=user_id, card_id=card_id, emi_doc=doc)
    if schedule_rows:
        await db[COL_EMI_SCHEDULE].insert_many(schedule_rows)
    await audit_log(action="CREDIT_CARD_EMI_PLAN_CREATED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "emi_id": str(result.inserted_id), "principal": principal, "tenure": tenure_months})
    return _serialize(doc)


async def build_emi_schedule(*, user_id: str, card_id: str, emi_doc: dict[str, Any]) -> list[dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    start_date = _to_utc(emi_doc.get("start_date")) or _now()
    principal_outstanding = _normalize_amount(emi_doc.get("principal"))
    rows: list[dict[str, Any]] = []
    current = start_date
    for installment_no in range(1, int(emi_doc.get("tenure_months") or 0) + 1):
        breakdown = calculate_emi_breakdown(
            opening_principal=principal_outstanding,
            annual_rate=float(emi_doc.get("interest_rate_annual") or 0.0),
            gst_rate=float(emi_doc.get("gst_rate") or 18.0),
            emi_amount=float(emi_doc.get("emi_amount") or 0.0),
        )
        rows.append({
            "user_id": user_oid,
            "emi_id": emi_doc.get("_id"),
            "card_id": card_oid,
            "installment_no": installment_no,
            "bill_cycle_key": _cycle_key(current),
            "due_date": current,
            "opening_principal": principal_outstanding,
            "principal_component": breakdown["principal"],
            "interest_component": breakdown["interest"],
            "gst_component": breakdown["gst"],
            "emi_amount": _normalize_amount(emi_doc.get("emi_amount")),
            "closing_principal": breakdown["closing_principal"],
            "status": "pending",
        })
        principal_outstanding = breakdown["closing_principal"]
        month = current.month + 1
        year = current.year
        if month == 13:
            month = 1
            year += 1
        current = current.replace(year=year, month=month, day=min(current.day, _days_in_month(year, month)))
    return rows


async def list_emi_plans(*, user_id: str, card_id: str) -> list[dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    emis = await db[COL_EMIS].find({"user_id": user_oid, "card_id": card_oid, "deleted_at": None}).sort("created_at", -1).to_list(length=200)
    return [_serialize(emi) for emi in emis]


async def update_emi_plan(*, user_id: str, card_id: str, emi_id: str, payload: Any, request=None) -> dict[str, Any]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    emi_oid = _to_object_id(emi_id, label="emi")
    emi = await db[COL_EMIS].find_one({"_id": emi_oid, "user_id": user_oid, "card_id": card_oid, "deleted_at": None})
    if not emi:
        raise NotFoundError("EMI plan not found")
    updates = {"updated_at": _now()}
    for field in ["title", "status"]:
        value = getattr(payload, field, None)
        if value is not None:
            updates[field] = value.strip() if isinstance(value, str) else value
    for field in ["interest_rate_annual", "gst_rate"]:
        value = getattr(payload, field, None)
        if value is not None:
            updates[field] = float(value)
    if getattr(payload, "tenure_months", None) is not None:
        updates["tenure_months"] = int(payload.tenure_months)
    await db[COL_EMIS].update_one({"_id": emi_oid}, {"$set": updates})
    await audit_log(action="CREDIT_CARD_EMI_PLAN_UPDATED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "emi_id": emi_id, "fields": sorted(k for k in updates.keys() if k != "updated_at")})
    updated = await db[COL_EMIS].find_one({"_id": emi_oid})
    return _serialize(updated)


async def delete_emi_plan(*, user_id: str, card_id: str, emi_id: str, request=None) -> None:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    emi_oid = _to_object_id(emi_id, label="emi")
    emi = await db[COL_EMIS].find_one({"_id": emi_oid, "user_id": user_oid, "card_id": card_oid, "deleted_at": None})
    if not emi:
        raise NotFoundError("EMI plan not found")
    now = _now()
    await db[COL_EMIS].update_one({"_id": emi_oid}, {"$set": {"deleted_at": now, "updated_at": now, "status": "closed"}})
    await db[COL_EMI_SCHEDULE].update_many({"emi_id": emi_oid}, {"$set": {"status": "cancelled"}})
    await audit_log(action="CREDIT_CARD_EMI_PLAN_DELETED", request=request, user={"user_id": user_id}, meta={"card_id": card_id, "emi_id": emi_id})


async def get_emi_schedule(*, user_id: str, card_id: str, emi_id: str) -> list[dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    card_oid = _to_object_id(card_id, label="card")
    emi_oid = _to_object_id(emi_id, label="emi")
    rows = await db[COL_EMI_SCHEDULE].find({"user_id": user_oid, "card_id": card_oid, "emi_id": emi_oid}).sort("installment_no", 1).to_list(length=240)
    return [_serialize(row) for row in rows]


async def get_credit_card_account_insights(*, user_id: str) -> dict[str, dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    cards = await db[COL_CARDS].find({"user_id": user_oid, "deleted_at": None, "source_account_id": {"$exists": True}}).to_list(length=200)
    insights: dict[str, dict[str, Any]] = {}

    for card in cards:
        source_account_id = card.get("source_account_id")
        if not source_account_id:
            continue

        card_id = str(card["_id"])
        utilization = await calculate_card_utilization(user_id=user_id, card_id=card_id)
        estimated_bill = await calculate_estimated_bill(user_id=user_id, card_id=card_id)
        latest_bill = await db[COL_BILLS].find_one(
            {"user_id": user_oid, "card_id": card["_id"]},
            sort=[("statement_date", -1)],
        )
        recent_bills = await db[COL_BILLS].find(
            {"user_id": user_oid, "card_id": card["_id"]}
        ).sort("statement_date", -1).to_list(length=6)

        recent_bill_rows = []
        for bill in recent_bills:
            recent_bill_rows.append({
                "id": str(bill.get("_id")) if bill.get("_id") else None,
                "cycle_key": bill.get("cycle_key"),
                "statement_date": bill.get("statement_date"),
                "due_date": bill.get("due_date"),
                "final_amount": _normalize_amount(bill.get("final_amount")),
                "minimum_due": _normalize_amount(bill.get("minimum_due")),
                "paid_amount": _normalize_amount(bill.get("paid_amount")),
                "outstanding_amount": _normalize_amount(bill.get("outstanding_amount")),
                "payment_status": bill.get("payment_status") or "unpaid",
            })

        insights[str(source_account_id)] = {
            "card_id": card_id,
            "utilization": utilization,
            "estimated_bill": {
                "cycle_key": estimated_bill.get("cycle_key"),
                "estimated_amount": _normalize_amount(estimated_bill.get("estimated_amount")),
                "minimum_due": _normalize_amount(estimated_bill.get("minimum_due")),
                "due_date": estimated_bill.get("due_date"),
                "transaction_count": int(estimated_bill.get("transaction_count") or 0),
                "emi_component_count": int(estimated_bill.get("emi_component_count") or 0),
            },
            "latest_bill": _serialize(latest_bill) if latest_bill else None,
            "recent_bills": recent_bill_rows,
        }

    return insights


async def get_multi_card_summary(*, user_id: str) -> dict[str, Any]:
    cards = await list_credit_cards(user_id=user_id)
    totals = {
        "total_cards": len(cards),
        "total_limit": 0.0,
        "total_outstanding": 0.0,
        "total_statement_due": 0.0,
        "utilization_percent": 0.0,
        "upcoming_due_count": 0,
        "active_emi_count": 0,
        "cards": [],
    }
    user_oid = _to_object_id(user_id, label="user")
    now = _now()
    for card in cards:
        util = await calculate_card_utilization(user_id=user_id, card_id=card["id"])
        latest_bill = await db[COL_BILLS].find_one({"user_id": user_oid, "card_id": _to_object_id(card["id"], label="card")}, sort=[("statement_date", -1)])
        emi_count = await db[COL_EMIS].count_documents({"user_id": user_oid, "card_id": _to_object_id(card["id"], label="card"), "status": "active", "deleted_at": None})
        totals["total_limit"] += util["total_limit"]
        totals["total_outstanding"] += util["outstanding"]
        totals["active_emi_count"] += emi_count
        if latest_bill:
            totals["total_statement_due"] += _normalize_amount(latest_bill.get("outstanding_amount"))
            if latest_bill.get("payment_status") != "paid" and latest_bill.get("due_date") and latest_bill["due_date"] >= now:
                totals["upcoming_due_count"] += 1
        totals["cards"].append({
            "card": card,
            "utilization": util,
            "latest_bill": _serialize(latest_bill) if latest_bill else None,
            "active_emi_count": emi_count,
            "warning": "high_utilization" if util["utilization_percent"] >= 75 else None,
        })
    if totals["total_limit"]:
        totals["utilization_percent"] = _normalize_amount((totals["total_outstanding"] / totals["total_limit"]) * 100)
    totals["total_limit"] = _normalize_amount(totals["total_limit"])
    totals["total_outstanding"] = _normalize_amount(totals["total_outstanding"])
    totals["total_statement_due"] = _normalize_amount(totals["total_statement_due"])
    return totals


async def get_liability_forecast(*, user_id: str, months: int = 3) -> list[dict[str, Any]]:
    user_oid = _to_object_id(user_id, label="user")
    cards = await db[COL_CARDS].find({"user_id": user_oid, "deleted_at": None, "status": "active"}).to_list(length=200)
    today = _now()
    month_map: dict[str, dict[str, Any]] = defaultdict(lambda: {"cycle_key": "", "projected_bill_amount": 0.0, "projected_emi_amount": 0.0, "projected_due_date": None})
    for offset in range(months):
        month = today.month + offset
        year = today.year
        while month > 12:
            month -= 12
            year += 1
        anchor = datetime(year, month, min(today.day, _days_in_month(year, month)), tzinfo=UTC)
        cycle_key = anchor.strftime("%Y-%m")
        month_map[cycle_key]["cycle_key"] = cycle_key
    for card in cards:
        for cycle_key in list(month_map.keys()):
            bill = await db[COL_BILLS].find_one({"user_id": user_oid, "card_id": card["_id"], "cycle_key": cycle_key})
            if bill:
                month_map[cycle_key]["projected_bill_amount"] += _normalize_amount(bill.get("outstanding_amount"))
                month_map[cycle_key]["projected_due_date"] = (bill.get("due_date") or month_map[cycle_key]["projected_due_date"])
            emi_rows = await db[COL_EMI_SCHEDULE].find({"user_id": user_oid, "card_id": card["_id"], "bill_cycle_key": cycle_key, "status": {"$in": ["pending", "projected"]}}).to_list(length=200)
            month_map[cycle_key]["projected_emi_amount"] += sum(_normalize_amount(r.get("emi_amount")) for r in emi_rows)
    out = []
    for cycle_key in sorted(month_map.keys()):
        row = month_map[cycle_key]
        row["projected_bill_amount"] = _normalize_amount(row["projected_bill_amount"])
        row["projected_emi_amount"] = _normalize_amount(row["projected_emi_amount"])
        row["projected_due_date"] = row["projected_due_date"].isoformat() if isinstance(row["projected_due_date"], datetime) else row["projected_due_date"]
        out.append(row)
    return out


async def schedule_bill_alerts(*, user_id: str, bill_id: str, bill_doc: dict[str, Any] | None = None) -> None:
    user_oid = _to_object_id(user_id, label="user")
    bill = bill_doc or await db[COL_BILLS].find_one({"_id": _to_object_id(bill_id, label="bill"), "user_id": user_oid})
    if not bill:
        raise NotFoundError("Bill not found")
    due_date = bill.get("due_date")
    if not due_date:
        return
    reminders = []
    for days_left in (21, 14, 7, 3, 2, 1):
        scheduled_for = due_date - timedelta(days=days_left)
        reminders.append({
            "user_id": user_oid,
            "card_id": bill.get("card_id"),
            "bill_id": bill.get("_id"),
            "alert_type": "due_reminder",
            "scheduled_for": scheduled_for,
            "sent_at": None,
            "status": "scheduled",
            "channel": "in_app",
            "meta": {"days_left": days_left},
            "created_at": _now(),
            "updated_at": _now(),
        })
    if reminders:
        await db[COL_ALERTS].insert_many(reminders)


async def run_bill_generation_job() -> int:
    cards = await db[COL_CARDS].find({"deleted_at": None, "status": "active", "statement_generation_mode": "auto"}).to_list(length=500)
    generated = 0
    today = _now()
    for card in cards:
        cycle = _get_billing_cycle(card, today)
        if cycle.statement_date.date() != today.date():
            continue
        existing = await db[COL_BILLS].find_one({"card_id": card["_id"], "cycle_key": cycle.cycle_key})
        if existing:
            continue
        await generate_bill_snapshot(user_id=str(card["user_id"]), card_id=str(card["_id"]))
        generated += 1
    return generated


async def run_due_alert_job() -> int:
    today = _now()
    alerts = await db[COL_ALERTS].find({"status": "scheduled", "scheduled_for": {"$lte": today}}).to_list(length=2000)
    sent = 0
    for alert in alerts:
        bill = await db[COL_BILLS].find_one({"_id": alert.get("bill_id")})
        if not bill or bill.get("payment_status") == "paid":
            await db[COL_ALERTS].update_one({"_id": alert["_id"]}, {"$set": {"status": "cancelled", "updated_at": _now()}})
            continue
        await db[COL_ALERTS].update_one({"_id": alert["_id"]}, {"$set": {"status": "sent", "sent_at": _now(), "updated_at": _now()}})
        sent += 1
    return sent


async def run_interest_and_late_fee_job() -> int:
    today = _now()
    overdue_bills = await db[COL_BILLS].find({"payment_status": {"$in": ["unpaid", "partial"]}, "due_date": {"$lt": today}}).to_list(length=1000)
    processed = 0
    for bill in overdue_bills:
        if bill.get("late_fee_applied") and bill.get("interest_applied"):
            continue
        outstanding = _normalize_amount(bill.get("outstanding_amount"))
        if outstanding <= 0:
            continue
        late_fee = 0.0 if bill.get("late_fee_applied") else (100.0 if outstanding <= 500 else 500.0 if outstanding <= 5000 else 1200.0)
        interest = 0.0 if bill.get("interest_applied") else _normalize_amount(outstanding * 0.42 / 365)
        gst = _normalize_amount(interest * 0.18)
        card_id = bill.get("card_id")
        user_id = bill.get("user_id")
        for txn_type, amount in (("late_fee", late_fee), ("interest", interest), ("gst", gst)):
            if amount <= 0:
                continue
            await db[COL_TXNS].insert_one({
                "user_id": user_id,
                "card_id": card_id,
                "bill_id": bill.get("_id"),
                "txn_type": txn_type,
                "amount": amount,
                "txn_date": today,
                "posted_date": today,
                "merchant": None,
                "category": txn_type,
                "description": f"Auto {txn_type.replace('_', ' ')}",
                "source": "system",
                "status": "posted",
                "is_emi": False,
                "emi_details": None,
                "emi_id": None,
                "bill_cycle_key": bill.get("cycle_key"),
                "frozen_in_bill": True,
                "meta": {},
                "created_at": _now(),
                "updated_at": _now(),
                "deleted_at": None,
            })
        await db[COL_BILLS].update_one({"_id": bill["_id"]}, {"$set": {"late_fee_applied": True, "interest_applied": True, "updated_at": _now()}, "$inc": {"final_amount": late_fee + interest + gst, "outstanding_amount": late_fee + interest + gst}})
        processed += 1
    return processed


async def run_emi_schedule_job() -> int:
    emis = await db[COL_EMIS].find({"deleted_at": None, "status": "active"}).to_list(length=1000)
    created = 0
    for emi in emis:
        schedule_rows = await db[COL_EMI_SCHEDULE].count_documents({"emi_id": emi["_id"]})
        if schedule_rows:
            continue
        rows = await build_emi_schedule(user_id=str(emi["user_id"]), card_id=str(emi["card_id"]), emi_doc=emi)
        if rows:
            await db[COL_EMI_SCHEDULE].insert_many(rows)
            created += len(rows)
    return created
