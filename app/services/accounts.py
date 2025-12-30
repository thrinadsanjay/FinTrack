from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from bson import ObjectId
from app.db.mongo import db
from pymongo.errors import DuplicateKeyError
from fastapi import HTTPException



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
    opening_balance: float,
):
    opening_balance = normalize_amount(opening_balance)

    doc = {
        "user_id": ObjectId(user_id),
        "name": name,
        "bank_name": bank_name,
        "type": acc_type,
        "opening_balance": opening_balance,
        "balance": round(opening_balance, 2),
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


async def update_account(
    *,
    user_id: str,
    account_id: str,
    name: str,
    bank_name: str,
    acc_type: str,
):
    await db.accounts.update_one(
        {
            "_id": ObjectId(account_id),
            "user_id": ObjectId(user_id),
        },
        {
            "$set": {
                "name": name,
                "bank_name": bank_name,
                "type": acc_type,
                "updated_at": datetime.utcnow(),
            }
        },
    )


async def delete_account(
    *,
    user_id: str,
    account_id: str,
):
    await db.accounts.delete_one({
        "_id": ObjectId(account_id),
        "user_id": ObjectId(user_id),
    })