from bson import ObjectId
from datetime import datetime, timedelta, timezone
from app.db.mongo import db
from app.services.audit import audit_log
from app.core.guards import (
    is_within_edit_window,
    can_restore_today,
    RESTORE_WINDOW_HOURS,
)

UTC = timezone.utc


# ======================================================
# CREATE TRANSACTION
# ======================================================
async def create_transaction(
    *,
    user_id: str,
    account_id: str,
    amount: float,
    tx_type: str,
    category_code: str,
    subcategory_code: str,
    description: str,
    target_account_id: str | None = None,
    request=None,
):
    if amount <= 0:
        raise Exception("Amount must be positive")

    user_oid = ObjectId(user_id)
    source_oid = ObjectId(account_id)

    now = datetime.now(UTC)

    # -----------------------------
    # Validate category
    # -----------------------------
    category = await db.categories.find_one(
        {"code": category_code, "type": tx_type, "is_system": True}
    )
    if not category:
        raise Exception("Invalid category")

    sub = next(
        (s for s in category["subcategories"] if s["code"] == subcategory_code),
        None,
    )
    if not sub:
        raise Exception("Invalid subcategory")

    # -----------------------------
    # Fetch source account
    # -----------------------------
    source = await db.accounts.find_one(
        {"_id": source_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not source:
        raise Exception("Account not found")

    # ======================================================
    # TRANSFER
    # ======================================================
    if tx_type == "transfer":
        if not target_account_id:
            raise Exception("Target account required")

        target_oid = ObjectId(target_account_id)
        if target_oid == source_oid:
            raise Exception("Source and target cannot be same")

        target = await db.accounts.find_one(
            {"_id": target_oid, "user_id": user_oid, "deleted_at": None}
        )
        if not target:
            raise Exception("Target account not found")

        if source["balance"] < amount:
            raise Exception("Insufficient balance")

        transfer_id = ObjectId()

        out_tx = {
            "transfer_id": transfer_id,
            "user_id": user_oid,
            "account_id": source_oid,
            "type": "transfer_out",
            "amount": amount,
            "description": description,
            "category": {"code": category["code"], "name": category["name"]},
            "subcategory": {"code": sub["code"], "name": sub["name"]},
            "created_at": now,
            "deleted_at": None,
        }

        in_tx = {
            "transfer_id": transfer_id,
            "user_id": user_oid,
            "account_id": target_oid,
            "type": "transfer_in",
            "amount": amount,
            "description": description,
            "category": {"code": category["code"], "name": category["name"]},
            "subcategory": {"code": sub["code"], "name": sub["name"]},
            "created_at": now,
            "deleted_at": None,
        }

        await db.transactions.insert_many([out_tx, in_tx])

        await db.accounts.update_one(
            {"_id": source_oid}, {"$inc": {"balance": -amount}}
        )
        await db.accounts.update_one(
            {"_id": target_oid}, {"$inc": {"balance": amount}}
        )

        await audit_log(
            action="TRANSFER_CREATED",
            request=request,
            user={"user_id": user_id},
            meta={
                "transfer_id": str(transfer_id),
                "amount": amount,
                "from": str(source_oid),
                "to": str(target_oid),
            },
        )

        return transfer_id

    # ======================================================
    # CREDIT / DEBIT
    # ======================================================
    delta = amount if tx_type == "credit" else -amount

    tx = {
        "user_id": user_oid,
        "account_id": source_oid,
        "type": tx_type,
        "amount": amount,
        "description": description,
        "category": {"code": category["code"], "name": category["name"]},
        "subcategory": {"code": sub["code"], "name": sub["name"]},
        "created_at": now,
        "deleted_at": None,
    }

    result = await db.transactions.insert_one(tx)

    await db.accounts.update_one(
        {"_id": source_oid}, {"$inc": {"balance": delta}}
    )

    await audit_log(
        action="TRANSACTION_CREATED",
        request=request,
        user={"user_id": user_id},
        meta={
            "transaction_id": str(result.inserted_id),
            "amount": amount,
            "delta": delta,
        },
    )

    return result.inserted_id


# ======================================================
# GET USER TRANSACTIONS
# ======================================================
async def get_user_transactions(
    *,
    user_id: str,
    account_id: str | None = None,
    tx_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category_code: str | None = None,
    subcategory_code: str | None = None,
):
    user_oid = ObjectId(user_id)
    now = datetime.now(UTC)

    query = {
        "user_id": user_oid,
        "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$gte": now - timedelta(hours=RESTORE_WINDOW_HOURS)}},
        ],
    }

    if account_id:
        query["account_id"] = ObjectId(account_id)

    if tx_type == "transfer":
        query["type"] = {"$in": ["transfer_in", "transfer_out"]}
    elif tx_type:
        query["type"] = tx_type

    if category_code:
        query["category.code"] = category_code

    if subcategory_code:
        query["subcategory.code"] = subcategory_code

    if date_from or date_to:
        query["created_at"] = {}
        if date_from:
            query["created_at"]["$gte"] = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
        if date_to:
            query["created_at"]["$lte"] = datetime.fromisoformat(date_to).replace(tzinfo=UTC)

    txs = await db.transactions.find(query).sort("created_at", -1).to_list(None)

    grouped = {}
    result = []

    for tx in txs:
        # -----------------------------
        # TRANSFER (group in + out)
        # -----------------------------
        if tx.get("transfer_id"):
            tid = str(tx["transfer_id"])

            if tid not in grouped:
                grouped[tid] = {
                    "transfer_id": tid,
                    "type": "transfer",
                    "amount": abs(tx["amount"]),
                    "created_at": tx["created_at"],
                    "from_account": None,
                    "to_account": None,

                    # ✅ display-only fields
                    "category_display": tx.get("category", {}).get("name"),
                    "subcategory_display": tx.get("subcategory", {}).get("name"),
                    "description": tx.get("description"),
                }

            if tx["type"] == "transfer_out":
                grouped[tid]["from_account"] = tx["account_id"]
            else:
                grouped[tid]["to_account"] = tx["account_id"]

        # -----------------------------
        # NORMAL TRANSACTIONS
        # -----------------------------
        else:
            tx["category_display"] = tx.get("category", {}).get("name")
            tx["subcategory_display"] = tx.get("subcategory", {}).get("name")
            result.append(tx)

    result.extend(grouped.values())
    result.sort(key=lambda x: x["created_at"], reverse=True)
    return result


# ======================================================
# DELETE TRANSACTION (SOFT)
# ======================================================
async def delete_transaction(
    *,
    user_id: str,
    transaction_id: str,
    transfer_id: str | None = None,
    request=None,
):
    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)
    now = datetime.now(UTC)

    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not tx:
        raise Exception("Transaction not found")

    if tx.get("transfer_id"):
        raise Exception("Transfers must be deleted as a unit")

    if not is_within_edit_window(tx["created_at"]):
        raise Exception("Edit window expired")

    amount = tx["amount"]

    delta = -amount if tx["type"] == "credit" else amount

    await db.accounts.update_one(
        {"_id": tx["account_id"]},
        {"$inc": {"balance": delta}},
    )

    await db.transactions.update_one(
        {"_id": tx_oid},
        {"$set": {"deleted_at": now}},
    )

    await audit_log(
        action="TRANSACTION_DELETED",
        request=request,
        user={"user_id": user_id},
        meta={
            "transaction_id": transaction_id,
            "amount": amount,
        },
    )


# ======================================================
# EDIT TRANSACTION
# ======================================================
async def edit_transaction(
    *,
    user_id: str,
    transaction_id: str,
    new_amount: float,
    new_category_code: str,
    new_subcategory_code: str,
    new_account_id: str,
    new_description: str,
    request=None,
):
    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)
    new_account_oid = ObjectId(new_account_id)

    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not tx:
        raise Exception("Transaction not found")

    if tx.get("transfer_id"):
        raise Exception("Transfers cannot be edited")

    if not is_within_edit_window(tx["created_at"]):
        raise Exception("Edit window expired")

    old_amount = tx["amount"]
    old_account_oid = tx["account_id"]
    tx_type = tx["type"]

    if tx_type == "credit":
        delta = new_amount - old_amount
    else:
        delta = old_amount - new_amount

    if old_account_oid != new_account_oid:
        rollback = -old_amount if tx_type == "credit" else old_amount
        apply = new_amount if tx_type == "credit" else -new_amount

        await db.accounts.update_one(
            {"_id": old_account_oid}, {"$inc": {"balance": rollback}}
        )
        await db.accounts.update_one(
            {"_id": new_account_oid}, {"$inc": {"balance": apply}}
        )
    else:
        await db.accounts.update_one(
            {"_id": old_account_oid}, {"$inc": {"balance": delta}}
        )

    # -----------------------------
    # Validate category
    # -----------------------------
    category = await db.categories.find_one(
        {
            "code": new_category_code,
            "type": tx_type,
            "is_system": True,
        }
    )
    if not category:
        raise Exception("Invalid category")

    sub = next(
        (s for s in category["subcategories"] if s["code"] == new_subcategory_code),
        None,
    )
    if not sub:
        raise Exception("Invalid subcategory")

    await db.transactions.update_one(
        {"_id": tx_oid},
        {
            "$set": {
                "amount": new_amount,
                "account_id": new_account_oid,
                "description": new_description,
                "category": {"code": category["code"], "name": category["name"]},
                "subcategory": {"code": sub["code"], "name": sub["name"]},
                "updated_at": datetime.now(UTC),
            }
        },
    )

    await audit_log(
        action="TRANSACTION_EDITED",
        request=request,
        user={"user_id": user_id},
        meta={
            "transaction_id": transaction_id,
            "old_amount": old_amount,
            "new_amount": new_amount,
            "old_account": str(old_account_oid),
            "new_account": str(new_account_oid),
            "old_description": tx.get("description", ""),
            "new_description": new_description,
        },
    )


# ======================================================
# RESTORE TRANSACTION
# ======================================================
async def restore_transaction(
    *,
    user_id: str,
    transaction_id: str,
    request=None,
):
    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)
    now = datetime.now(timezone.utc)

    # 1️⃣ Fetch transaction
    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid}
    )
    if not tx:
        raise Exception("Transaction not found")

    if not tx.get("deleted_at"):
        raise Exception("Transaction is not deleted")

    if not can_restore_today(tx["deleted_at"]):
        raise Exception("Restore window expired")

    # 2️⃣ Restore account balance
    amount = tx["amount"]

    if tx["type"] == "credit":
        delta = amount
    elif tx["type"] == "debit":
        delta = -amount
    else:
        raise Exception("Transfers must be restored via transfer logic")

    await db.accounts.update_one(
        {"_id": tx["account_id"]},
        {"$inc": {"balance": delta}},
    )

    # 3️⃣ Clear deleted flag
    await db.transactions.update_one(
        {"_id": tx_oid},
        {
            "$set": {
                "deleted_at": None,
                "restored_at": now,
            }
        },
    )

    # 4️⃣ Audit
    await audit_log(
        action="TRANSACTION_RESTORED",
        request=request,
        user={"user_id": user_id},
        meta={
            "transaction_id": str(tx_oid),
            "account_id": str(tx["account_id"]),
            "amount": amount,
            "type": tx["type"],
        },
    )
