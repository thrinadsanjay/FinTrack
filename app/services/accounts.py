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
from app.helpers.notification_payloads import (
    account_created_payload,
    account_deleted_payload,
    account_updated_payload,
)
from app.core.errors import NotFoundError, ConflictError, ValidationError
from app.services.notifications import upsert_notification


# ======================================================
# HELPERS
# ======================================================

def _now():
    return datetime.now(timezone.utc)


def normalize_amount(value: float) -> float:
    return round_money(value)


def normalize_last4(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    if len(digits) != 4:
        raise ValidationError("Last 4 digits must be exactly 4 numbers")
    return digits


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
    billing_cycle_start_day: int | None,
    billing_cycle_end_day: int | None,
    due_day: int | None,
    bill_generation_date: date | datetime | None,
    payment_due_date: date | datetime | None,
) -> dict:
    if acc_type != "credit_card":
        return {
            "credit_limit": None,
            "minimum_due": None,
            "statement_balance": None,
            "card_network": None,
            "billing_cycle_start_day": None,
            "billing_cycle_end_day": None,
            "due_day": None,
            "bill_generation_date": None,
            "payment_due_date": None,
        }
    return {
        "credit_limit": _normalize_optional_amount(credit_limit) or 0.0,
        "minimum_due": _normalize_optional_amount(minimum_due) or 0.0,
        "statement_balance": _normalize_optional_amount(statement_balance) or 0.0,
        "card_network": (card_network or "visa").strip().lower() if acc_type == "credit_card" else None,
        "billing_cycle_start_day": int(billing_cycle_start_day or 1),
        "billing_cycle_end_day": int(billing_cycle_end_day or 30),
        "due_day": int(due_day or 5),
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
    billing_cycle_start_day: int | None = None,
    billing_cycle_end_day: int | None = None,
    due_day: int | None = None,
    bill_generation_date: date | datetime | None = None,
    payment_due_date: date | datetime | None = None,
    original_principal: float | None = None,
    interest_rate: float | None = None,
    emi_amount: float | None = None,
    emi_day: int | None = None,
    tenure_months: int | None = None,
    start_date: date | None = None,
    last4: str | None = None,
    loan_kind: str | None = None,
    request: Request | None = None,
):
    balance = normalize_amount(balance)
    if acc_type == "loan":
        balance = abs(balance)

    doc = {
        "user_id": ObjectId(user_id),
        "name": name or bank_name,
        "bank_name": bank_name,
        "type": acc_type,
        "balance": balance,
        "last4": normalize_last4(last4),
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
            billing_cycle_start_day=billing_cycle_start_day,
            billing_cycle_end_day=billing_cycle_end_day,
            due_day=due_day,
            bill_generation_date=bill_generation_date,
            payment_due_date=payment_due_date,
        )
    )
    if acc_type == "loan":
        from app.helpers.accounts_ui import normalize_loan_kind
        from app.services.loans import loan_fields

        doc["loan_kind"] = normalize_loan_kind(loan_kind, name=doc.get("name"))
        doc.update(
            loan_fields(
                outstanding=balance,
                original_principal=original_principal,
                interest_rate=interest_rate,
                emi_amount=emi_amount,
                emi_day=emi_day,
                tenure_months=tenure_months,
                start_date=start_date,
            )
        )

    try:
        result = await db.accounts.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=400,
            detail="You already have an account with this name."
        )

    if acc_type == "credit_card":
        from app.services.credit_cards import sync_credit_card_account_record

        await sync_credit_card_account_record(user_id=user_id, account_id=str(result.inserted_id))

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
            "billing_cycle_start_day": doc.get("billing_cycle_start_day"),
            "billing_cycle_end_day": doc.get("billing_cycle_end_day"),
            "due_day": doc.get("due_day"),
            "bill_generation_date": doc.get("bill_generation_date").isoformat() if doc.get("bill_generation_date") else None,
            "payment_due_date": doc.get("payment_due_date").isoformat() if doc.get("payment_due_date") else None,
        },
    )

    await upsert_notification(
        user_id=ObjectId(user_id),
        **account_created_payload(
            account_id=str(result.inserted_id),
            name=doc.get("name") or bank_name,
            acc_type=acc_type,
        ),
    )

    return result.inserted_id


# ======================================================
# UPDATE (NAME ONLY)
# ======================================================

_BANK_TYPES = {"savings", "current", "wallet", "cash", "investment", "other"}


async def update_account_name(
    *,
    user_id: str,
    account_id: str,
    name: str,
    last4: str | None = None,
    bank_name: str | None = None,
    acc_type: str | None = None,
    balance: float | None = None,
    request: Request | None = None,
):
    account_oid = ObjectId(account_id)
    user_oid = ObjectId(user_id)

    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not account:
        raise NotFoundError("Account not found or access denied")
    if account.get("type") in {"credit_card", "loan"}:
        raise ValidationError("Use the card or loan editor for this account")

    updates = {"name": name.strip(), "updated_at": _now()}
    if last4 is not None:
        updates["last4"] = normalize_last4(last4)
    if bank_name is not None and bank_name.strip():
        updates["bank_name"] = bank_name.strip()
    if acc_type:
        key = acc_type.strip().lower()
        if key not in _BANK_TYPES:
            raise ValidationError("Choose a bank, wallet, cash, or investment type")
        updates["type"] = key
    if balance is not None:
        updates["balance"] = normalize_amount(balance)

    await db.accounts.update_one(
        {"_id": account_oid},
        {"$set": updates}
    )

    await audit_log(
        action="ACCOUNT_RENAMED",
        request=request,
        user={"user_id": user_id},
        meta={
            "account_id": str(account_oid),
            "old_name": account["name"],
            "new_name": updates["name"],
            "last4": updates.get("last4", account.get("last4")),
            "bank_name": updates.get("bank_name", account.get("bank_name")),
            "type": updates.get("type", account.get("type")),
        },
    )

    await upsert_notification(
        user_id=user_oid,
        **account_updated_payload(
            account_id=str(account_oid),
            stamp=_now().strftime("%Y%m%d%H%M%S"),
            name=updates["name"],
        ),
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
    billing_cycle_start_day: int | None,
    billing_cycle_end_day: int | None,
    due_day: int | None,
    bill_generation_date: date | datetime | None,
    payment_due_date: date | datetime | None,
    last4: str | None = None,
    name: str | None = None,
    bank_name: str | None = None,
    outstanding: float | None = None,
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
        "billing_cycle_start_day": int(billing_cycle_start_day or account.get("billing_cycle_start_day") or 1),
        "billing_cycle_end_day": int(billing_cycle_end_day or account.get("billing_cycle_end_day") or 30),
        "due_day": int(due_day or account.get("due_day") or 5),
        "bill_generation_date": _normalize_optional_due_date(bill_generation_date),
        "payment_due_date": _normalize_optional_due_date(payment_due_date),
        "updated_at": _now(),
    }
    if last4 is not None:
        updates["last4"] = normalize_last4(last4)
    if name is not None and name.strip():
        updates["name"] = name.strip()
    if bank_name is not None and bank_name.strip():
        updates["bank_name"] = bank_name.strip()
    if outstanding is not None:
        updates["balance"] = -abs(normalize_amount(outstanding))

    await db.accounts.update_one({"_id": account_oid}, {"$set": updates})

    from app.services.credit_cards import sync_credit_card_account_record

    await sync_credit_card_account_record(user_id=user_id, account_id=account_id)

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
            "billing_cycle_start_day": updates["billing_cycle_start_day"],
            "billing_cycle_end_day": updates["billing_cycle_end_day"],
            "due_day": updates["due_day"],
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

    if account.get("type") == "credit_card":
        from app.services.credit_cards import archive_credit_card_account_record

        await archive_credit_card_account_record(user_id=user_id, account_id=account_id)

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

    await upsert_notification(
        user_id=user_oid,
        **account_deleted_payload(
            account_id=str(account_oid),
            stamp=_now().strftime("%Y%m%d%H%M%S"),
            name=account.get("name") or "Account",
        ),
    )
