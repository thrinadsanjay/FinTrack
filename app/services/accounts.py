from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from bson import ObjectId
from app.db.mongo import db
from pymongo.errors import DuplicateKeyError
from fastapi import HTTPException, Request
from app.services.audit import audit_log



def normalize_amount(value: float) -> float:
    return float(
        Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


async def get_accounts(user_id: str):
    cursor = db.accounts.find(
        {"user_id": ObjectId(user_id)}
    ).sort("created_at", -1)

    accounts = []
    async for acc in cursor:
        accounts.append(acc)
    return accounts


async def create_account(
    *,
    user_id: str,
    name: str,
    bank_name: str,
    acc_type: str,
    balance: float,
):
    balance = normalize_amount(balance)

    doc = {
        "user_id": ObjectId(user_id),
        "name": name,
        "bank_name": bank_name,
        "type": acc_type,
        "balance": round(balance, 2),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    try:
        await db.accounts.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=400,
            detail="You already have an account with this name."
        )
    
    await audit_log(
        action="ACCOUNT_CREATED",
        # request=request,
        user={
            "user_id": user_id,
        },
        meta={
            #"account_id": str(result.inserted_id),
            "bank_name": bank_name,
            "account_type": acc_type,
            "initial_balance": balance,
        },
    )
    
async def update_account(
    user_id: str,
    account_id: str,
    name: str,
    balance: float,
    request=Request,   # 👈 pass request for audit context
):
    account_oid = ObjectId(account_id)
    user_oid = ObjectId(user_id)

    # 1️⃣ Fetch current account (needed for audit)
    
    account = await db.accounts.find_one(
        {
            "_id": account_oid,
            "user_id": user_oid,
        }
    )

    if not account:
        
        raise Exception(f"Account not found or access denied")
        

    old_balance = account.get("balance", 0)

    # 2️⃣ Perform update
    result = await db.accounts.update_one(
        {
            "_id": account_oid,
            "user_id": user_oid,
        },
        {
            "$set": {
                "name": name,
                "balance": balance,
            }
        },
    )

    # 3️⃣ Audit ONLY if balance changed
    if old_balance != balance:
        await audit_log(
            action="ACCOUNT_BALANCE_UPDATED",
            request=request,
            user={
                "user_id": user_id,
                "username": account.get("username"),  # optional
            },
            meta={
                "account_id": str(account_oid),
                "old_balance": old_balance,
                "new_balance": balance,
                "delta": balance - old_balance,
            },
        )

    return result


async def delete_account(
    user_id: str,
    account_id: str,
    request=Request,   # 👈 for audit
):
    account_oid = ObjectId(account_id)
    user_oid = ObjectId(user_id)

    # 1️⃣ Fetch account BEFORE delete (needed for audit)
    account = await db.accounts.find_one(
        {
            "_id": account_oid,
            "user_id": user_oid,
        }
    )

    if not account:
        raise Exception("Account not found or access denied")

    # 2️⃣ Delete account
    result = await db.accounts.delete_one(
        {
            "_id": account_oid,
            "user_id": user_oid,
        }
    )

    # 3️⃣ AUDIT: ACCOUNT DELETED
    await audit_log(
        action="ACCOUNT_DELETED",
        request=request,
        user={
            "user_id": user_id,
        },
        meta={
            "account_id": str(account_oid),
            "name": account.get("name"),
            "bank_name": account.get("bank_name"),
            "account_type": account.get("type"),
            "balance_at_delete": account.get("balance"),
        },
    )
    return result