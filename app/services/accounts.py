"""
Business logic for account management.

Responsibilities:
- Create, update, delete accounts
- Balance normalization
- Credit-card metadata and EMI tracking
- Safety checks
- Audit logging

Must NOT:
- Render templates
- Redirect responses
"""

from datetime import datetime, timezone, date, time
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from fastapi import HTTPException, Request

from app.db.mongo import db
from app.services.audit import audit_log
from app.helpers.money import round_money
from app.core.errors import NotFoundError, ConflictError, ValidationError


# ======================================================
# HELPERS
# ======================================================

def _now():
    return datetime.now(timezone.utc)


def normalize_amount(value: float) -> float:
    return round_money(value)


def _normalize_optional_amount(value: float | None) -> float | None:
    if value is None:
        return None
    return normalize_amount(value)


def _normalize_optional_due_date(value: date | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _credit_card_meta(
    *,
    acc_type: str,
    credit_limit: float | None,
    minimum_due: float | None,
    statement_balance: float | None,
    card_network: str | None,
    bill_generation_date: date | datetime | None,
    payment_due_date: date | datetime | None,
) -> dict:
    if acc_type != "credit_card":
        return {
            "credit_limit": None,
            "minimum_due": None,
            "statement_balance": None,
            "card_network": None,
            "bill_generation_date": None,
            "payment_due_date": None,
        }
    return {
        "credit_limit": _normalize_optional_amount(credit_limit) or 0.0,
        "minimum_due": _normalize_optional_amount(minimum_due) or 0.0,
        "statement_balance": _normalize_optional_amount(statement_balance) or 0.0,
        "card_network": (card_network or "visa").strip().lower() if acc_type == "credit_card" else None,
        "bill_generation_date": _normalize_optional_due_date(bill_generation_date),
        "payment_due_date": _normalize_optional_due_date(payment_due_date),
    }


def _credit_card_outstanding(balance: float | int | None) -> float:
    value = float(balance or 0)
    if value >= 0:
        return 0.0
    return round_money(abs(value))


# ======================================================
# READ
# ======================================================

async def get_accounts(user_id: str):
    cursor = db.accounts.find(
        {"user_id": ObjectId(user_id), "deleted_at": None}
    ).sort("created_at", 1)

    return [acc async for acc in cursor]


async def get_credit_card_emi_map(user_id: str) -> dict[str, list[dict]]:
    cursor = (
        db.credit_card_emis
        .find(
            {
                "user_id": ObjectId(user_id),
                "deleted_at": None,
            }
        )
        .sort([("next_due_date", 1), ("created_at", -1)])
    )

    out: dict[str, list[dict]] = {}
    async for item in cursor:
        account_id = item.get("account_id")
        out.setdefault(account_id, []).append(item)
    return out


# ======================================================
# CREATE
# ======================================================

async def create_account(
    *,
    user_id: str,
    name: str | None,
    bank_name: str,
    acc_type: str,
    balance: float,
    credit_limit: float | None = None,
    minimum_due: float | None = None,
    statement_balance: float | None = None,
    card_network: str | None = None,
    bill_generation_date: date | datetime | None = None,
    payment_due_date: date | datetime | None = None,
    request: Request | None = None,
):
    balance = normalize_amount(balance)

    doc = {
        "user_id": ObjectId(user_id),
        "name": name or bank_name,
        "bank_name": bank_name,
        "type": acc_type,
        "balance": balance,
        "created_at": _now(),
        "updated_at": _now(),
        "deleted_at": None,
    }
    doc.update(
        _credit_card_meta(
            acc_type=acc_type,
            credit_limit=credit_limit,
            minimum_due=minimum_due,
            statement_balance=statement_balance,
            card_network=card_network,
            bill_generation_date=bill_generation_date,
            payment_due_date=payment_due_date,
        )
    )

    try:
        result = await db.accounts.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=400,
            detail="You already have an account with this name."
        )

    await audit_log(
        action="ACCOUNT_CREATED",
        request=request,
        user={"user_id": user_id},
        meta={
            "account_id": str(result.inserted_id),
            "bank_name": bank_name,
            "account_type": acc_type,
            "initial_balance": balance,
            "credit_limit": doc.get("credit_limit"),
            "minimum_due": doc.get("minimum_due"),
            "statement_balance": doc.get("statement_balance"),
            "card_network": doc.get("card_network"),
            "bill_generation_date": doc.get("bill_generation_date").isoformat() if doc.get("bill_generation_date") else None,
            "payment_due_date": doc.get("payment_due_date").isoformat() if doc.get("payment_due_date") else None,
        },
    )

    return result.inserted_id


# ======================================================
# UPDATE (NAME ONLY)
# ======================================================

async def update_account_name(
    *,
    user_id: str,
    account_id: str,
    name: str,
    request: Request | None = None,
):
    account_oid = ObjectId(account_id)
    user_oid = ObjectId(user_id)

    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not account:
        raise NotFoundError("Account not found or access denied")

    await db.accounts.update_one(
        {"_id": account_oid},
        {"$set": {"name": name, "updated_at": _now()}}
    )

    await audit_log(
        action="ACCOUNT_RENAMED",
        request=request,
        user={"user_id": user_id},
        meta={
            "account_id": str(account_oid),
            "old_name": account["name"],
            "new_name": name,
        },
    )


# ======================================================
# UPDATE (BALANCE ONLY)
# ======================================================

async def update_account_balance(
    *,
    user_id: str,
    account_id: str,
    balance: float,
    request: Request | None = None,
):
    account_oid = ObjectId(account_id)
    user_oid = ObjectId(user_id)

    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not account:
        raise NotFoundError("Account not found or access denied")

    balance = normalize_amount(balance)

    await db.accounts.update_one(
        {"_id": account_oid},
        {"$set": {"balance": balance, "updated_at": _now()}}
    )

    await audit_log(
        action="ACCOUNT_BALANCE_UPDATED",
        request=request,
        user={"user_id": user_id},
        meta={
            "account_id": str(account_oid),
            "old_balance": account.get("balance", 0),
            "new_balance": balance,
        },
    )


async def update_credit_card_settings(
    *,
    user_id: str,
    account_id: str,
    credit_limit: float | None,
    minimum_due: float | None,
    statement_balance: float | None,
    card_network: str | None,
    bill_generation_date: date | datetime | None,
    payment_due_date: date | datetime | None,
    request: Request | None = None,
):
    account_oid = ObjectId(account_id)
    user_oid = ObjectId(user_id)

    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not account:
        raise NotFoundError("Account not found or access denied")
    if account.get("type") != "credit_card":
        raise ValidationError("Credit card settings can only be updated for credit card accounts")

    updates = {
        "credit_limit": _normalize_optional_amount(credit_limit) or 0.0,
        "minimum_due": _normalize_optional_amount(minimum_due) or 0.0,
        "statement_balance": _normalize_optional_amount(statement_balance) or 0.0,
        "card_network": (card_network or account.get("card_network") or "visa").strip().lower(),
        "bill_generation_date": _normalize_optional_due_date(bill_generation_date),
        "payment_due_date": _normalize_optional_due_date(payment_due_date),
        "updated_at": _now(),
    }

    await db.accounts.update_one({"_id": account_oid}, {"$set": updates})

    await audit_log(
        action="ACCOUNT_CREDIT_CARD_UPDATED",
        request=request,
        user={"user_id": user_id},
        meta={
            "account_id": account_id,
            "credit_limit": updates["credit_limit"],
            "minimum_due": updates["minimum_due"],
            "statement_balance": updates["statement_balance"],
            "card_network": updates["card_network"],
            "bill_generation_date": updates["bill_generation_date"].isoformat() if updates["bill_generation_date"] else None,
            "payment_due_date": updates["payment_due_date"].isoformat() if updates["payment_due_date"] else None,
            "current_outstanding": _credit_card_outstanding(account.get("balance", 0)),
        },
    )


async def add_credit_card_emi(
    *,
    user_id: str,
    account_id: str,
    title: str,
    total_amount: float,
    monthly_amount: float,
    total_installments: int,
    remaining_installments: int,
    interest_rate: float | None,
    next_due_date: date | datetime | None,
    request: Request | None = None,
):
    if not title.strip():
        raise ValidationError("EMI title is required")
    if total_amount <= 0 or monthly_amount <= 0:
        raise ValidationError("EMI amounts must be positive")
    if total_installments <= 0:
        raise ValidationError("Total installments must be positive")
    if remaining_installments < 0 or remaining_installments > total_installments:
        raise ValidationError("Remaining installments must be between 0 and total installments")
    if interest_rate is not None and interest_rate < 0:
        raise ValidationError("Interest rate cannot be negative")

    account_oid = ObjectId(account_id)
    user_oid = ObjectId(user_id)
    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not account:
        raise NotFoundError("Account not found or access denied")
    if account.get("type") != "credit_card":
        raise ValidationError("EMIs can only be added for credit card accounts")

    now = _now()
    next_due_value = _normalize_optional_due_date(next_due_date)
    status = "active" if remaining_installments > 0 else "closed"
    doc = {
        "user_id": user_oid,
        "account_id": account_oid,
        "title": title.strip(),
        "total_amount": normalize_amount(total_amount),
        "monthly_amount": normalize_amount(monthly_amount),
        "total_installments": int(total_installments),
        "remaining_installments": int(remaining_installments),
        "interest_rate": normalize_amount(interest_rate or 0.0),
        "next_due_date": next_due_value,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
    }
    result = await db.credit_card_emis.insert_one(doc)

    await audit_log(
        action="CREDIT_CARD_EMI_CREATED",
        request=request,
        user={"user_id": user_id},
        meta={
            "emi_id": str(result.inserted_id),
            "account_id": account_id,
            "title": doc["title"],
            "monthly_amount": doc["monthly_amount"],
            "remaining_installments": doc["remaining_installments"],
            "interest_rate": doc["interest_rate"],
        },
    )
    return result.inserted_id


async def update_credit_card_emi(
    *,
    user_id: str,
    emi_id: str,
    title: str,
    total_amount: float,
    monthly_amount: float,
    total_installments: int,
    remaining_installments: int,
    interest_rate: float | None,
    next_due_date: date | datetime | None,
    request: Request | None = None,
):
    if not title.strip():
        raise ValidationError("EMI title is required")
    if total_amount <= 0 or monthly_amount <= 0:
        raise ValidationError("EMI amounts must be positive")
    if total_installments <= 0:
        raise ValidationError("Total installments must be positive")
    if remaining_installments < 0 or remaining_installments > total_installments:
        raise ValidationError("Remaining installments must be between 0 and total installments")
    if interest_rate is not None and interest_rate < 0:
        raise ValidationError("Interest rate cannot be negative")

    emi_oid = ObjectId(emi_id)
    user_oid = ObjectId(user_id)
    emi = await db.credit_card_emis.find_one(
        {"_id": emi_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not emi:
        raise NotFoundError("EMI not found or access denied")

    updates = {
        "title": title.strip(),
        "total_amount": normalize_amount(total_amount),
        "monthly_amount": normalize_amount(monthly_amount),
        "total_installments": int(total_installments),
        "remaining_installments": int(remaining_installments),
        "interest_rate": normalize_amount(interest_rate or 0.0),
        "next_due_date": _normalize_optional_due_date(next_due_date),
        "status": "active" if remaining_installments > 0 else "closed",
        "updated_at": _now(),
    }

    await db.credit_card_emis.update_one({"_id": emi_oid}, {"$set": updates})

    await audit_log(
        action="CREDIT_CARD_EMI_UPDATED",
        request=request,
        user={"user_id": user_id},
        meta={
            "emi_id": emi_id,
            "account_id": str(emi.get("account_id")),
            "title": updates["title"],
            "monthly_amount": updates["monthly_amount"],
            "remaining_installments": updates["remaining_installments"],
            "interest_rate": updates["interest_rate"],
        },
    )


async def delete_credit_card_emi(
    *,
    user_id: str,
    emi_id: str,
    request: Request | None = None,
):
    emi_oid = ObjectId(emi_id)
    user_oid = ObjectId(user_id)
    emi = await db.credit_card_emis.find_one(
        {"_id": emi_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not emi:
        raise NotFoundError("EMI not found or access denied")

    await db.credit_card_emis.update_one(
        {"_id": emi_oid},
        {"$set": {"deleted_at": _now(), "updated_at": _now()}},
    )

    await audit_log(
        action="CREDIT_CARD_EMI_DELETED",
        request=request,
        user={"user_id": user_id},
        meta={
            "emi_id": emi_id,
            "account_id": str(emi.get("account_id")),
            "title": emi.get("title"),
        },
    )


# ======================================================
# SOFT DELETE ACCOUNT
# ======================================================

async def delete_account(
    *,
    user_id: str,
    account_id: str,
    request: Request | None = None,
):
    account_oid = ObjectId(account_id)
    user_oid = ObjectId(user_id)

    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not account:
        raise NotFoundError("Account not found or access denied")

    tx_exists = await db.transactions.find_one(
        {"account_id": account_oid, "deleted_at": None}
    )
    if tx_exists:
        raise ConflictError("Account has active transactions and cannot be deleted")

    await db.accounts.update_one(
        {"_id": account_oid},
        {"$set": {"deleted_at": _now()}}
    )
    await db.credit_card_emis.update_many(
        {"account_id": account_oid, "user_id": user_oid, "deleted_at": None},
        {"$set": {"deleted_at": _now(), "updated_at": _now()}},
    )

    await audit_log(
        action="ACCOUNT_DELETED",
        request=request,
        user={"user_id": user_id},
        meta={
            "account_id": str(account_oid),
            "name": account["name"],
            "bank_name": account["bank_name"],
            "account_type": account["type"],
            "balance_at_delete": account["balance"],
        },
    )
