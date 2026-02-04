"""
Business logic for account management.

Responsibilities:
- Create, update, delete accounts
- Balance normalization
- Safety checks
- Audit logging

Must NOT:
- Render templates
- Redirect responses
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from fastapi import HTTPException, Request

from app.db.mongo import db
from app.services.audit import audit_log


# ======================================================
# HELPERS
# ======================================================

def _now():
    return datetime.now(timezone.utc)


def normalize_amount(value: float) -> float:
    return float(
        Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


# ======================================================
# READ
# ======================================================

async def get_accounts(user_id: str):
    cursor = db.accounts.find(
        {"user_id": ObjectId(user_id), "deleted_at": None}
    ).sort("created_at", 1)

    return [acc async for acc in cursor]


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
        raise Exception("Account not found or access denied")

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
        raise Exception("Account not found or access denied")

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
        raise Exception("Account not found or access denied")

    tx_exists = await db.transactions.find_one(
        {"account_id": account_oid, "deleted_at": None}
    )
    if tx_exists:
        raise Exception("Account has active transactions and cannot be deleted")

    await db.accounts.update_one(
        {"_id": account_oid},
        {"$set": {"deleted_at": _now()}}
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
