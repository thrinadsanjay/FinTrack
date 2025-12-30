from datetime import datetime, timezone
from bson import ObjectId
from app.db.mongo import db
from fastapi import HTTPException, status

async def create_transaction(
    *,
    user_id: ObjectId,
    account_id: str,
    amount: int,
    tx_type: str,  # "debit" or "credit"
    category: str | None = None,
    note: str | None = None,
):
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Amount must be positive",
        )

    account_oid = ObjectId(account_id)

    # 🔐 Step 1: Verify ownership
    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_id}
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # 🔐 Step 2: Debit safety check
    if tx_type == "debit" and account["balance"] < amount:
        raise HTTPException(
            status_code=400,
            detail="Insufficient balance",
        )

    # 🔁 Step 3: Atomic balance update
    delta = amount if tx_type == "credit" else -amount

    update_result = await db.accounts.update_one(
        {"_id": account_oid, "user_id": user_id},
        {"$inc": {"balance": delta}},
    )

    if update_result.modified_count != 1:
        raise HTTPException(
            status_code=409,
            detail="Balance update failed",
        )

    # 🧾 Step 4: Insert transaction
    tx_doc = {
        "user_id": user_id,
        "account_id": account_oid,
        "type": tx_type,
        "amount": amount,
        "category": category,
        "note": note,
        "created_at": datetime.now(timezone.utc),
    }

    result = await db.transactions.insert_one(tx_doc)
    tx_doc["_id"] = result.inserted_id

    return tx_doc
