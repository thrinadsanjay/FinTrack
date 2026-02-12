"""
Business logic for transactions.

Responsibilities:
- Validate input
- Update balances
- Insert transactions
- Handle transfers
- Write audit logs
- Create recurring rules (metadata only)

This module MUST NOT:
- Render templates
- Redirect responses
- Access session directly
"""

import re
from bson import ObjectId
from datetime import datetime, timedelta, timezone, date
from app.db.mongo import db
from app.services.audit import audit_log
from app.core.guards import (
    is_within_edit_window,
    can_restore_today,
    RESTORE_WINDOW_HOURS,
)
from app.services.recurring_deposit import RecurringDepositService
from app.services.notifications import upsert_notification

UTC = timezone.utc

# ======================================================
# CREATE TRANSACTION
# ======================================================
# async def create_transaction(
#     *,
#     user_id: str,
#     account_id: str,
#     amount: float,
#     tx_type: str,
#     category_code: str,
#     subcategory_code: str,
#     description: str,
#     target_account_id: str | None = None,
#     recurring: dict | None = None,
#     request=None,
# ):
# async def create_transaction(
#     *,
#     user_id: str,
#     account_id: str,
#     amount: float,
#     tx_type: str,
#     mode: str,
#     category_code: str,
#     subcategory_code: str,
#     description: str,
#     target_account_id: str | None = None,
#     is_recurring: bool = False,
#     frequency: str | None = None,
#     interval: int = 1,
#     start_date: date | None = None,
#     end_date: date | None = None,
#     request=None,
# ):
#     """
#     Creates a transaction and optionally a recurring rule.

#     Returns:
#     - ObjectId (transaction_id OR transfer_id)
#     """

#     if amount <= 0:
#         raise Exception("Amount must be positive")

#     # is_recurring = recurring is not None

#     user_oid = ObjectId(user_id)
#     source_oid = ObjectId(account_id)
#     now = datetime.now(UTC)

#     # -----------------------------
#     # Validate category
#     # -----------------------------
#     category = await db.categories.find_one(
#         {"code": category_code, "type": tx_type, "is_system": True}
#     )
#     if not category:
#         raise Exception("Invalid category")

#     sub = next(
#         (s for s in category["subcategories"] if s["code"] == subcategory_code),
#         None,
#     )
#     if not sub:
#         raise Exception("Invalid subcategory")

#     # -----------------------------
#     # Fetch source account
#     # -----------------------------
#     source = await db.accounts.find_one(
#         {"_id": source_oid, "user_id": user_oid, "deleted_at": None}
#     )
#     if not source:
#         raise Exception("Account not found")

#     # ======================================================
#     # TRANSFER (UNCHANGED)
#     # ======================================================
#     if tx_type == "transfer":
#         if not target_account_id:
#             raise Exception("Target account required")

#         target_oid = ObjectId(target_account_id)
#         if target_oid == source_oid:
#             raise Exception("Source and target cannot be same")

#         target = await db.accounts.find_one(
#             {"_id": target_oid, "user_id": user_oid, "deleted_at": None}
#         )
#         if not target:
#             raise Exception("Target account not found")

#         if source["balance"] < amount:
#             raise Exception("Insufficient balance")

#         transfer_id = ObjectId()

#         await db.transactions.insert_many([
#             {
#                 "transfer_id": transfer_id,
#                 "user_id": user_oid,
#                 "account_id": source_oid,
#                 "type": "transfer_out",
#                 "mode": mode,
#                 "amount": amount,
#                 "description": description,
#                 "category": {"code": category["code"], "name": category["name"]},
#                 "subcategory": {"code": sub["code"], "name": sub["name"]},
#                 "created_at": now,
#                 "deleted_at": None,
#             },
#             {
#                 "transfer_id": transfer_id,
#                 "user_id": user_oid,
#                 "account_id": target_oid,
#                 "type": "transfer_in",
#                 "mode": mode,
#                 "amount": amount,
#                 "description": description,
#                 "category": {"code": category["code"], "name": category["name"]},
#                 "subcategory": {"code": sub["code"], "name": sub["name"]},
#                 "created_at": now,
#                 "deleted_at": None,
#             },
#         ])

#         await db.accounts.update_one({"_id": source_oid}, {"$inc": {"balance": -amount}})
#         await db.accounts.update_one({"_id": target_oid}, {"$inc": {"balance": amount}})

#         await audit_log(
#             action="TRANSFER_CREATED",
#             request=request,
#             user={"user_id": user_id},
#             meta={"transfer_id": str(transfer_id), "amount": amount},
#         )

#         return transfer_id

#     # ======================================================
#     # CREDIT / DEBIT (UNCHANGED CORE LOGIC)
#     # ======================================================
#     delta = amount if tx_type == "credit" else -amount

#     tx_doc = {
#         "user_id": user_oid,
#         "account_id": source_oid,
#         "type": tx_type,
#         "mode": mode,
#         "amount": amount,
#         "description": description,
#         "category": {"code": category["code"], "name": category["name"]},
#         "subcategory": {"code": sub["code"], "name": sub["name"]},
#         "created_at": now,
#         "deleted_at": None,
#     }

#     result = await db.transactions.insert_one(tx_doc)

#     await db.accounts.update_one({"_id": source_oid}, {"$inc": {"balance": delta}})

#     # ======================================================
#     # 🆕 NEW: CREATE RECURRING RULE (IF CHECKED)
#     # ======================================================
#     if is_recurring:
#         """
#         recurring = {
#             "frequency": "monthly",
#             "start_date": date
#         }
#         """

#         start_date_value = (
#             datetime.fromisoformat(start_date).date()
#             if start_date else date.today()
#         )

#         end_date_value = (
#             datetime.fromisoformat(end_date).date()
#             if end_date else None
#         )

#         await RecurringDepositService.create(
#             user_id=user_oid,
#             account_id=account_id,
#             amount=amount,
#             # mode=mode,
#             # tx_type=tx_type,
#             # category_code=category_code,
#             # subcategory_code=subcategory_code,
#             # description=description,
#             frequency=frequency,
#             interval=interval,
#             start_date=start_date_value,
#             end_date=end_date_value,
#             #source_transaction_id=result.inserted_id,
#         )


#     await audit_log(
#         action="TRANSACTION_CREATED",
#         request=request,
#         user={"user_id": user_id},
#         meta={"transaction_id": str(result.inserted_id), "amount": amount},
#     )

#     return result.inserted_id
async def create_transaction(
    *,
    user_id: str,
    account_id: str,
    amount: float,
    tx_type: str,
    mode: str,
    category_code: str,
    subcategory_code: str,
    description: str,
    target_account_id: str | None = None,
    is_recurring: bool = False,
    frequency: str | None = None,
    interval: int = 1,
    start_date: date | None = None,
    end_date: date | None = None,
    request=None,
):
    """
    High-level transaction creator.
    - Always creates a real transaction immediately
    - Optionally creates a recurring rule
    """

    if amount <= 0:
        raise Exception("Amount must be positive")

    user_oid = ObjectId(user_id)

    # -----------------------------
    # Validate category & subcategory
    # -----------------------------
    category, subcategory = await _validate_category(
        category_code=category_code,
        subcategory_code=subcategory_code,
        tx_type=tx_type,
    )

    # -----------------------------
    # Create transaction (now)
    # -----------------------------
    if tx_type == "transfer":
        tx_id = await _add_transfer_transaction(
            user_oid=user_oid,
            source_account_id=account_id,
            target_account_id=target_account_id,
            amount=amount,
            mode=mode,
            description=description,
            category=category,
            subcategory=subcategory,
            request=request,
        )
    else:
        tx_id = await _add_single_transaction(
            user_oid=user_oid,
            account_id=account_id,
            amount=amount,
            tx_type=tx_type,
            mode=mode,
            description=description,
            category=category,
            subcategory=subcategory,
            request=request,
        )

    # -----------------------------
    # Create recurring rule (if needed)
    # -----------------------------
    if is_recurring:
        if not frequency:
            raise Exception("Recurring frequency is required")

        await _add_recurring_transaction(
            user_oid=user_oid,
            account_id=account_id,
            amount=amount,
            tx_type=tx_type,
            mode=mode,
            description=description,
            category=category,
            subcategory=subcategory,
            frequency=frequency,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            source_transaction_id=tx_id,
        )

    success_title = "Transaction added successfully"
    if tx_type == "transfer":
        success_title = "Transfer added successfully"

    await upsert_notification(
        user_id=user_oid,
        key=f"tx_added:{str(tx_id)}",
        notif_type="success",
        title=success_title,
        message=f"₹ {amount} has been recorded.",
        is_read=True,
    )

    return tx_id

async def _validate_category(*, category_code: str, subcategory_code: str, tx_type: str):
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

    return (
        {"code": category["code"], "name": category["name"]},
        {"code": sub["code"], "name": sub["name"]},
    )

async def _add_single_transaction(
    *,
    user_oid: ObjectId,
    account_id: str,
    amount: float,
    tx_type: str,
    mode: str,
    description: str,
    category: dict,
    subcategory: dict,
    request=None,
):
    now = datetime.now(UTC)
    account_oid = ObjectId(account_id)

    delta = amount if tx_type == "credit" else -amount

    tx_doc = {
        "user_id": user_oid,
        "account_id": account_oid,
        "type": tx_type,
        "mode": mode,
        "amount": amount,
        "description": description,
        "category": category,
        "subcategory": subcategory,
        "created_at": now,
        "deleted_at": None,
    }

    result = await db.transactions.insert_one(tx_doc)
    await db.accounts.update_one({"_id": account_oid}, {"$inc": {"balance": delta}})

    await audit_log(
        action="TRANSACTION_CREATED",
        request=request,
        user={"user_id": str(user_oid)},
        meta={"transaction_id": str(result.inserted_id), "amount": amount},
    )

    return result.inserted_id


async def _add_transfer_transaction(
    *,
    user_oid: ObjectId,
    source_account_id: str,
    target_account_id: str | None,
    amount: float,
    mode: str,
    description: str,
    category: dict,
    subcategory: dict,
    request=None,
):
    if not target_account_id:
        raise Exception("Target account required")

    source_oid = ObjectId(source_account_id)
    target_oid = ObjectId(target_account_id)

    if source_oid == target_oid:
        raise Exception("Source and target cannot be same")

    transfer_id = ObjectId()
    now = datetime.now(UTC)

    await db.transactions.insert_many([
        {
            "transfer_id": transfer_id,
            "user_id": user_oid,
            "account_id": source_oid,
            "type": "transfer_out",
            "mode": mode,
            "amount": amount,
            "description": description,
            "category": category,
            "subcategory": subcategory,
            "created_at": now,
            "deleted_at": None,
        },
        {
            "transfer_id": transfer_id,
            "user_id": user_oid,
            "account_id": target_oid,
            "type": "transfer_in",
            "mode": mode,
            "amount": amount,
            "description": description,
            "category": category,
            "subcategory": subcategory,
            "created_at": now,
            "deleted_at": None,
        },
    ])

    await db.accounts.update_one({"_id": source_oid}, {"$inc": {"balance": -amount}})
    await db.accounts.update_one({"_id": target_oid}, {"$inc": {"balance": amount}})

    return transfer_id

async def _add_recurring_transaction(
    *,
    user_oid: ObjectId,
    account_id: str,
    amount: float,
    tx_type: str,
    mode: str,
    description: str,
    category: dict,
    subcategory: dict,
    frequency: str,
    interval: int,
    start_date: date | None,
    end_date: date | None,
    source_transaction_id: ObjectId,
):
    start_date_value = (
    datetime.fromisoformat(start_date).date()
    if start_date else date.today()
    )

    end_date_value = (
        datetime.fromisoformat(end_date).date()
        if end_date else None
    )


    await RecurringDepositService.create(
        user_id=user_oid,
        account_id=account_id,
        amount=amount,
        tx_type=tx_type,
        mode=mode,
        description=description,
        category=category,
        subcategory=subcategory,
        frequency=frequency,
        interval=interval,
        start_date=start_date_value,
        end_date=end_date_value,
        source_transaction_id=source_transaction_id,
    )


# ======================================================
# READ TRANSACTIONS (USED BY WEB)
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
    search: str | None = None,
    amount: float | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
):
    """
    Fetch user transactions for UI listing.

    NOTE:
    - Used by web layer
    - Handles soft-deletes and restore window
    """



    user_oid = ObjectId(user_id)
    now = datetime.now(timezone.utc)

    query = {
        "user_id": user_oid,
        "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$gte": now - timedelta(hours=RESTORE_WINDOW_HOURS)}},
        ],
    }

    if account_id:
        query["account_id"] = ObjectId(account_id)

    if tx_type:
        if tx_type == "transfer":
            query["type"] = {"$in": ["transfer_in", "transfer_out"]}
        else:
            query["type"] = tx_type

    if category_code:
        query["category.code"] = category_code

    if subcategory_code:
        query["subcategory.code"] = subcategory_code

    if amount is not None:
        query["amount"] = amount

    if search:
        query["description"] = {"$regex": re.escape(search), "$options": "i"}

    if date_from or date_to:
        query["created_at"] = {}
        if date_from:
            query["created_at"]["$gte"] = datetime.fromisoformat(date_from).replace(
                tzinfo=timezone.utc
            )
        if date_to:
            query["created_at"]["$lte"] = datetime.fromisoformat(date_to).replace(
                tzinfo=timezone.utc
            )

    sort_field = "created_at"
    if sort_by == "amount":
        sort_field = "amount"
    elif sort_by == "account":
        sort_field = "account_id"
    elif sort_by == "category":
        sort_field = "category.name"
    elif sort_by == "subcategory":
        sort_field = "subcategory.name"

    direction = -1 if (sort_dir or "desc").lower() == "desc" else 1

    cursor = (
        db.transactions
        .find(query)
        .sort(sort_field, direction)
    )

    transactions = []
    async for tx in cursor:
        transactions.append(tx)

    return transactions

# ======================================================
# DELETE TRANSACTION
# ======================================================

async def delete_transaction(
    *,
    user_id: str,
    transaction_id: str,
    request=None,
):
    from bson import ObjectId
    from datetime import datetime, timezone
    from app.core.guards import is_within_edit_window
    from app.db.mongo import db
    from app.services.audit import audit_log

    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)
    now = datetime.now(timezone.utc)

    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not tx:
        raise Exception("Transaction not found")

    if tx.get("transfer_id"):
        raise Exception("Transfers must be deleted as a unit")

    if not is_within_edit_window(tx["created_at"]):
        raise Exception("Edit window expired")

    delta = -tx["amount"] if tx["type"] == "credit" else tx["amount"]

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
        meta={"transaction_id": transaction_id},
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
    from bson import ObjectId
    from datetime import datetime, timezone
    from app.core.guards import can_restore_today
    from app.db.mongo import db
    from app.services.audit import audit_log

    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)
    now = datetime.now(timezone.utc)

    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid}
    )
    if not tx or not tx.get("deleted_at"):
        raise Exception("Transaction not deleted")

    if not can_restore_today(tx["deleted_at"]):
        raise Exception("Restore window expired")

    delta = tx["amount"] if tx["type"] == "credit" else -tx["amount"]

    await db.accounts.update_one(
        {"_id": tx["account_id"]},
        {"$inc": {"balance": delta}},
    )

    await db.transactions.update_one(
        {"_id": tx_oid},
        {
            "$set": {
                "deleted_at": None,
                "restored_at": now,
            }
        },
    )

    await audit_log(
        action="TRANSACTION_RESTORED",
        request=request,
        user={"user_id": user_id},
        meta={"transaction_id": transaction_id},
    )

# ======================================================
# EDIT TRANSACTION
# ======================================================

async def edit_transaction(
    *,
    user_id: str,
    transaction_id: str,
    new_account_id: str,
    new_amount: float,
    new_category_code: str,
    new_subcategory_code: str,
    new_description: str,
    request=None,
):
    from bson import ObjectId
    from datetime import datetime, timezone
    from app.core.guards import is_within_edit_window
    from app.db.mongo import db
    from app.services.audit import audit_log

    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)
    new_account_oid = ObjectId(new_account_id)

    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not tx:
        raise Exception("Transaction not found")

    if not is_within_edit_window(tx["created_at"]):
        raise Exception("Edit window expired")

    old_amount = tx["amount"]
    delta = (
        new_amount - old_amount
        if tx["type"] == "credit"
        else old_amount - new_amount
    )

    await db.accounts.update_one(
        {"_id": tx["account_id"]},
        {"$inc": {"balance": delta}},
    )

    await db.transactions.update_one(
        {"_id": tx_oid},
        {
            "$set": {
                "amount": new_amount,
                "account_id": new_account_oid,
                "description": new_description,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )

    await audit_log(
        action="TRANSACTION_EDITED",
        request=request,
        user={"user_id": user_id},
        meta={"transaction_id": transaction_id},
    )

__all__ = [
    "create_transaction",
    "get_user_transactions",
    "delete_transaction",
    "restore_transaction",
    "edit_transaction",
]
