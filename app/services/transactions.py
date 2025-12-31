from bson import ObjectId
from datetime import datetime
from app.db.mongo import db
from app.services.audit import audit_log
from collections import defaultdict

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
        {"_id": source_oid, "user_id": user_oid}
    )
    if not source:
        raise Exception("Source account not found")

    # ======================================================
    # TRANSFER LOGIC
    # ======================================================
    if tx_type == "transfer":
        if not target_account_id:
            raise Exception("Target account required")

        target_oid = ObjectId(target_account_id)

        if target_oid == source_oid:
            raise Exception("Source and target cannot be same")

        target = await db.accounts.find_one(
            {"_id": target_oid, "user_id": user_oid}
        )
        if not target:
            raise Exception("Target account not found")

        if source["balance"] < amount:
            raise Exception("Insufficient balance")

        transfer_id = ObjectId()
        now = datetime.utcnow()

        # 1️⃣ Insert OUT transaction
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
        }

        # 2️⃣ Insert IN transaction
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
        }

        await db.transactions.insert_many([out_tx, in_tx])

        # 3️⃣ Update balances
        await db.accounts.update_one(
            {"_id": source_oid},
            {"$inc": {"balance": -amount}},
        )
        await db.accounts.update_one(
            {"_id": target_oid},
            {"$inc": {"balance": amount}},
        )

        # 4️⃣ Audit (single event)
        await audit_log(
            action="ACCOUNT_TRANSFER",
            request=request,
            user={"user_id": user_id},
            meta={
                "transfer_id": str(transfer_id),
                "from_account": str(source_oid),
                "to_account": str(target_oid),
                "amount": amount,
                "source_balance_before": source["balance"],
                "source_balance_after": source["balance"] - amount,
                "target_balance_before": target["balance"],
                "target_balance_after": target["balance"] + amount,
            },
        )

        return transfer_id

    # ======================================================
    # NORMAL CREDIT / DEBIT
    # ======================================================
    delta = amount if tx_type == "credit" else -amount
    new_balance = source["balance"] + delta

    tx = {
        "user_id": user_oid,
        "account_id": source_oid,
        "type": tx_type,
        "amount": amount,
        "description": description,
        "category": {"code": category["code"], "name": category["name"]},
        "subcategory": {"code": sub["code"], "name": sub["name"]},
        "created_at": datetime.utcnow(),
    }

    result = await db.transactions.insert_one(tx)

    await db.accounts.update_one(
        {"_id": source_oid},
        {"$set": {"balance": new_balance}},
    )

    await audit_log(
        action="TRANSACTION_CREATED",
        request=request,
        user={"user_id": user_id},
        meta={
            "transaction_id": str(result.inserted_id),
            "account_id": str(source_oid),
            "amount": amount,
            "old_balance": source["balance"],
            "new_balance": new_balance,
        },
    )

    return result.inserted_id

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

    query = {"user_id": user_oid}

    # -------------------------
    # Account filter
    # -------------------------
    if account_id:
        query["account_id"] = ObjectId(account_id)

    # -------------------------
    # Type filter
    # -------------------------
    if tx_type == "transfer":
        query["type"] = {"$in": ["transfer_in", "transfer_out"]}
    elif tx_type in ("credit", "debit"):
        query["type"] = tx_type

    # -------------------------
    # Category filter
    # -------------------------
    if category_code:
        query["category.code"] = category_code

    # -------------------------
    # Subcategory filter
    # -------------------------
    if subcategory_code:
        query["subcategory.code"] = subcategory_code


    # -------------------------
    # Date range filter
    # -------------------------
    if date_from or date_to:
        query["created_at"] = {}

        if date_from:
            query["created_at"]["$gte"] = datetime.fromisoformat(date_from)

        if date_to:
            query["created_at"]["$lte"] = datetime.fromisoformat(date_to)

    cursor = db.transactions.find(query).sort("created_at", -1)
    txs = await cursor.to_list(length=None)

    # -------------------------
    # Group transfers
    # -------------------------
    grouped = {}
    result = []

    for tx in txs:
        if tx.get("transfer_id"):
            tid = str(tx["transfer_id"])
            if tid not in grouped:
                grouped[tid] = {
                    "transfer_id": tid,
                    "type": "transfer",
                    "amount": tx["amount"],
                    "category": tx["category"]["name"],
                    "subcategory": tx["subcategory"]["name"],
                    "created_at": tx["created_at"],
                    "from_account": None,
                    "to_account": None,
                }

            if tx["type"] == "transfer_out":
                grouped[tid]["from_account"] = tx["account_id"]
            elif tx["type"] == "transfer_in":
                grouped[tid]["to_account"] = tx["account_id"]
        else:
            result.append({
                "_id": tx["_id"],
                "type": tx["type"],
                "amount": tx["amount"],
                "category": tx["category"]["name"],
                "subcategory": tx["subcategory"]["name"],
                "account_id": tx["account_id"],
                "created_at": tx["created_at"],
                "category": {
                    "code": tx["category"]["code"],
                    "name": tx["category"]["name"],
                },
                "subcategory": {
                    "code": tx["subcategory"]["code"],
                    "name": tx["subcategory"]["name"],
                },
            })

    result.extend(grouped.values())
    result.sort(key=lambda x: x["created_at"], reverse=True)

    return result

async def delete_transaction(
    *,
    user_id: str,
    transaction_id: str,
    transfer_id: str | None = None,
    request=None,
):
    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)

    # 1️⃣ Fetch transaction
    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid}
    )

    if not tx:
        raise Exception("Transaction not found or access denied")

    # ======================================================
    # TRANSFER DELETE (rollback both legs)
    # ======================================================
    if tx.get("transfer_id"):
        transfer_id = tx["transfer_id"]

        txs = await db.transactions.find(
            {"transfer_id": transfer_id, "user_id": user_oid}
        ).to_list(length=None)

        if len(txs) != 2:
            raise Exception("Invalid transfer state")

        out_tx = next(t for t in txs if t["type"] == "transfer_out")
        in_tx = next(t for t in txs if t["type"] == "transfer_in")

        amount = out_tx["amount"]

        # Rollback balances
        await db.accounts.update_one(
            {"_id": out_tx["account_id"]},
            {"$inc": {"balance": amount}},
        )

        await db.accounts.update_one(
            {"_id": in_tx["account_id"]},
            {"$inc": {"balance": -amount}},
        )

        # Delete both records
        await db.transactions.delete_many(
            {"transfer_id": transfer_id}
        )

        # Audit
        await audit_log(
            action="TRANSACTION_TRANSFER_DELETED",
            request=request,
            user={"user_id": user_id},
            meta={
                "transfer_id": str(transfer_id),
                "amount": amount,
                "from_account": str(out_tx["account_id"]),
                "to_account": str(in_tx["account_id"]),
            },
        )

        return

    # ======================================================
    # NORMAL CREDIT / DEBIT
    # ======================================================
    account_id = tx["account_id"]
    amount = tx["amount"]

    # Rollback balance
    if tx["type"] == "credit":
        delta = -amount
    elif tx["type"] == "debit":
        delta = amount
    else:
        raise Exception("Unknown transaction type")

    await db.accounts.update_one(
        {"_id": account_id},
        {"$inc": {"balance": delta}},
    )

    # Delete transaction
    await db.transactions.delete_one(
        {"_id": tx_oid}
    )

    # Audit
    await audit_log(
        action="TRANSACTION_DELETED",
        request=request,
        user={"user_id": user_id},
        meta={
            "transaction_id": transaction_id,
            "type": tx["type"],
            "amount": amount,
            "account_id": str(account_id),
        },
    )


async def edit_transaction(
    *,
    user_id: str,
    transaction_id: str,
    new_amount: float,
    new_category_code: str,
    new_subcategory_code: str,
    new_account_id: str,
    request=None,
):
    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)
    new_account_oid = ObjectId(new_account_id)

    # 1️⃣ Fetch transaction
    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid}
    )

    if not tx:
        raise Exception("Transaction not found")

    if tx.get("transfer_id"):
        raise Exception("Transfers cannot be edited")

    if new_amount <= 0:
        raise Exception("Amount must be positive")

    old_amount = tx["amount"]
    old_account_oid = tx["account_id"]
    tx_type = tx["type"]  # credit / debit

    # 2️⃣ Validate category + subcategory

    # If category/subcategory not provided, keep existing
    category_code = new_category_code or tx["category"]["code"]
    subcategory_code = new_subcategory_code or tx["subcategory"]["code"]
    category = await db.categories.find_one(
        {
            "code": category_code,
            "type": tx_type,
            "is_system": True,
        }
    )

    if not category:
        raise Exception("Invalid category")

    sub = next(
        (s for s in category["subcategories"] if s["code"] == subcategory_code),
        None,
    )

    if not sub:
        raise Exception("Invalid subcategory")

    # 3️⃣ Compute balance delta
    if tx_type == "credit":
        delta = new_amount - old_amount
    else:  # debit
        delta = old_amount - new_amount

    # 4️⃣ If account changed → rollback + apply
    if old_account_oid != new_account_oid:
        # Rollback old account fully
        rollback = -old_amount if tx_type == "credit" else old_amount
        await db.accounts.update_one(
            {"_id": old_account_oid},
            {"$inc": {"balance": rollback}},
        )

        # Apply new amount to new account
        apply = new_amount if tx_type == "credit" else -new_amount
        await db.accounts.update_one(
            {"_id": new_account_oid},
            {"$inc": {"balance": apply}},
        )
    else:
        # Same account → apply delta
        await db.accounts.update_one(
            {"_id": old_account_oid},
            {"$inc": {"balance": delta}},
        )

    # 5️⃣ Update transaction
    await db.transactions.update_one(
        {"_id": tx_oid},
        {
            "$set": {
                "amount": new_amount,
                "account_id": new_account_oid,
                "category": {
                    "code": category["code"],
                    "name": category["name"],
                },
                "subcategory": {
                    "code": sub["code"],
                    "name": sub["name"],
                },
            }
        },
    )

    # 6️⃣ Audit
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
            "delta_applied": delta,
        },
    )
