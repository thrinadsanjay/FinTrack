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

from bson import ObjectId
from datetime import datetime, timezone, date
from app.db.mongo import db
from app.services.audit import audit_log
from app.helpers.recurring_schedule import (
    calculate_next_run,
    calculate_next_occurrence,
)
from app.helpers.account_balances import (
    apply_account_delta,
    apply_transfer_deltas,
    delta_for_delete,
    delta_for_edit,
    delta_for_tx,
)
from app.helpers.transaction_queries import (
    build_transactions_query,
    resolve_transactions_sort,
)
from app.helpers.transaction_retry import (
    is_retry_insufficient_funds,
    build_retry_pending_update,
    build_retry_resolved_update,
)
from app.helpers.transaction_docs import (
    build_failed_transaction_doc,
    build_single_transaction_doc,
    build_transfer_transaction_docs,
)
from app.helpers.notification_payloads import (
    retry_failed_payload,
    retry_success_payload,
    tx_added_payload,
    tx_deleted_payload,
    tx_failed_insufficient_payload,
    tx_restored_payload,
    tx_updated_payload,
)
from app.services.recurring_deposit import RecurringDepositService
from app.helpers.transaction_inputs import parse_date_value, validate_category
from app.services.notifications import upsert_notification
from app.services.metrics import increment_transaction
from app.helpers.money import round_money
from app.core.errors import ValidationError, NotFoundError, ConflictError

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
#         raise ValidationError("Amount must be positive")

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
#         raise NotFoundError("Account not found")

#     # ======================================================
#     # TRANSFER (UNCHANGED)
#     # ======================================================
#     if effective_tx_type == "transfer":
#         if not target_account_id:
#             raise ValidationError("Target account required")

#         target_oid = ObjectId(target_account_id)
#         if target_oid == source_oid:
#             raise ValidationError("Source and target cannot be same")

#         target = await db.accounts.find_one(
#             {"_id": target_oid, "user_id": user_oid, "deleted_at": None}
#         )
#         if not target:
#             raise NotFoundError("Target account not found")

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
    transfer_kind: str | None = None,
    credit_bill_id: str | None = None,
    is_recurring: bool = False,
    frequency: str | None = None,
    interval: int = 1,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    request=None,
):
    """
    High-level transaction creator.
    - Creates an immediate transaction for one-time entries
    - For recurring entries, creates only the rule (scheduler posts transactions)
    """

    if amount <= 0:
        raise ValidationError("Amount must be positive")

    amount = round_money(amount)

    user_oid = ObjectId(user_id)

    effective_tx_type = "transfer" if tx_type == "card_payment" else tx_type

    # -----------------------------
    # Validate category & subcategory
    # -----------------------------
    category, subcategory = await validate_category(
        category_code=category_code,
        subcategory_code=subcategory_code,
        tx_type=effective_tx_type,
    )

    source_account = await db.accounts.find_one(
        {"_id": ObjectId(account_id), "user_id": user_oid, "deleted_at": None},
        {"balance": 1, "name": 1},
    )
    if not source_account:
        raise NotFoundError("Account not found")

    target_account = None
    if effective_tx_type == "transfer":
        if not target_account_id:
            raise ValidationError("Target account required")
        target_account = await db.accounts.find_one(
            {"_id": ObjectId(target_account_id), "user_id": user_oid, "deleted_at": None},
            {"balance": 1, "name": 1},
        )
        if not target_account:
            raise NotFoundError("Target account not found")
        if str(target_account["_id"]) == str(source_account["_id"]):
            raise ValidationError("Source and target cannot be same")

    recurring_due_today = False
    if is_recurring:
        if not frequency:
            raise ValidationError("Recurring frequency is required")

        start_date_value = parse_date_value(start_date)
        end_date_value = parse_date_value(end_date)
        if not start_date_value:
            raise ValidationError("Start date is required")
        if end_date_value and end_date_value < start_date_value:
            raise ValidationError("End date cannot be before start date")

        # Always create the recurring rule first.
        await _add_recurring_transaction(
            user_oid=user_oid,
            account_id=account_id,
            amount=amount,
            tx_type=effective_tx_type,
            mode=mode,
            description=description,
            category=category,
            subcategory=subcategory,
            frequency=frequency,
            interval=interval,
            start_date=start_date_value,
            end_date=end_date_value,
            source_transaction_id=None,
        )

        next_due = calculate_next_occurrence(
            start_date=start_date_value,
            frequency=frequency,
            today=datetime.now(UTC).date(),
            include_today=True,
            skip_missed=True,
        )
        recurring_due_today = next_due.date() == datetime.now(UTC).date()
        if not recurring_due_today:
            return None

    # Fail debit/transfer when funds are insufficient, but keep a retryable failed row.
    if effective_tx_type == "debit" and source_account.get("balance", 0) < amount:
        failed_id = await _add_failed_transaction(
            user_oid=user_oid,
            account_id=account_id,
            amount=amount,
            tx_type=effective_tx_type,
            mode=mode,
            description=description,
            category=category,
            subcategory=subcategory,
            source="manual",
            failure_reason="insufficient_funds",
            request=request,
        )
        await upsert_notification(
            user_id=user_oid,
            **tx_failed_insufficient_payload(
                failed_id=str(failed_id),
                is_transfer=False,
                account_name=source_account.get("name", "Account"),
                balance=source_account.get("balance", 0),
                amount=amount,
            ),
        )
        return failed_id

    if effective_tx_type == "transfer" and source_account.get("balance", 0) < amount:
        failed_id = await _add_failed_transaction(
            user_oid=user_oid,
            account_id=account_id,
            amount=amount,
            tx_type="transfer_out",
            mode=mode,
            description=description,
            category=category,
            subcategory=subcategory,
            source="manual_transfer",
            failure_reason="insufficient_funds",
            target_account_id=target_account_id,
            request=request,
        )
        await upsert_notification(
            user_id=user_oid,
            **tx_failed_insufficient_payload(
                failed_id=str(failed_id),
                is_transfer=True,
                account_name=source_account.get("name", "Account"),
                balance=source_account.get("balance", 0),
                amount=amount,
            ),
        )
        return failed_id

    # -----------------------------
    # Create transaction (now)
    # -----------------------------
    if effective_tx_type == "transfer":
        tx_id = await _add_transfer_transaction(
            user_oid=user_oid,
            source_account_id=account_id,
            target_account_id=target_account_id,
            amount=amount,
            mode=mode,
            description=description,
            category=category,
            subcategory=subcategory,
            transfer_kind=transfer_kind,
            request=request,
        )
        if tx_type == "card_payment" and credit_bill_id:
            from app.services.credit_cards import record_bill_payment

            await record_bill_payment(
                user_id=user_id,
                card_id=target_account_id,
                bill_id=credit_bill_id,
                payload=type(
                    "CreditBillPaymentPayload",
                    (),
                    {
                        "amount": amount,
                        "payment_date": datetime.now(UTC).date(),
                        "source_account_id": account_id,
                        "payment_mode": mode,
                        "reference_no": description or None,
                    },
                )(),
                request=request,
            )
    else:
        tx_id = await _add_single_transaction(
            user_oid=user_oid,
            account_id=account_id,
            amount=amount,
            tx_type=effective_tx_type,
            mode=mode,
            description=description,
            category=category,
            subcategory=subcategory,
            request=request,
        )

    await upsert_notification(
        user_id=user_oid,
        **tx_added_payload(
            tx_id=str(tx_id),
            tx_type=effective_tx_type,
            amount=amount,
        ),
    )
    increment_transaction()

    return tx_id


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
    transfer_kind: str | None = None,
    request=None,
):
    now = datetime.now(UTC)
    account_oid = ObjectId(account_id)

    delta = delta_for_tx(tx_type, amount)

    tx_doc = build_single_transaction_doc(
        user_id=user_oid,
        account_id=account_oid,
        tx_type=tx_type,
        mode=mode,
        amount=amount,
        description=description,
        category=category,
        subcategory=subcategory,
        created_at=now,
    )

    result = await db.transactions.insert_one(tx_doc)
    await apply_account_delta(db=db, account_id=account_oid, delta=delta)

    await audit_log(
        action="TRANSACTION_CREATED",
        request=request,
        user={"user_id": str(user_oid)},
        meta={"transaction_id": str(result.inserted_id), "amount": amount},
    )

    return result.inserted_id


async def _add_failed_transaction(
    *,
    user_oid: ObjectId,
    account_id: str,
    amount: float,
    tx_type: str,
    mode: str,
    description: str,
    category: dict,
    subcategory: dict,
    source: str,
    failure_reason: str,
    target_account_id: str | None = None,
    request=None,
):
    now = datetime.now(UTC)
    tx_doc = build_failed_transaction_doc(
        user_id=user_oid,
        account_id=ObjectId(account_id),
        tx_type=tx_type,
        mode=mode,
        amount=amount,
        description=description,
        category=category,
        subcategory=subcategory,
        source=source,
        failure_reason=failure_reason,
        created_at=now,
        target_account_id=ObjectId(target_account_id) if target_account_id else None,
    )

    result = await db.transactions.insert_one(tx_doc)
    await audit_log(
        action="TRANSACTION_FAILED",
        request=request,
        user={"user_id": str(user_oid)},
        meta={
            "transaction_id": str(result.inserted_id),
            "amount": amount,
            "reason": failure_reason,
        },
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
    transfer_kind: str | None = None,
    request=None,
):
    if not target_account_id:
        raise ValidationError("Target account required")

    source_oid = ObjectId(source_account_id)
    target_oid = ObjectId(target_account_id)

    if source_oid == target_oid:
        raise ValidationError("Source and target cannot be same")

    transfer_id = ObjectId()
    now = datetime.now(UTC)

    await db.transactions.insert_many(
        build_transfer_transaction_docs(
            transfer_id=transfer_id,
            user_id=user_oid,
            source_account_id=source_oid,
            target_account_id=target_oid,
            mode=mode,
            amount=amount,
            description=description,
            category=category,
            subcategory=subcategory,
            created_at=now,
            source=transfer_kind,
        )
    )

    await apply_transfer_deltas(
        db=db,
        source_account_id=source_oid,
        target_account_id=target_oid,
        amount=amount,
    )

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
    start_date: date | str | None,
    end_date: date | str | None,
    source_transaction_id: ObjectId | None = None,
):
    start_date_value = parse_date_value(start_date) or date.today()
    end_date_value = parse_date_value(end_date)


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



    query = build_transactions_query(
        user_id=user_id,
        account_id=account_id,
        tx_type=tx_type,
        date_from=date_from,
        date_to=date_to,
        category_code=category_code,
        subcategory_code=subcategory_code,
        search=search,
        amount=amount,
    )
    sort_field, direction = resolve_transactions_sort(sort_by, sort_dir)

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
        raise NotFoundError("Transaction not found")
    if tx.get("is_failed"):
        raise ConflictError("Failed transactions cannot be deleted")

    if tx.get("transfer_id"):
        raise ConflictError("Transfers must be deleted as a unit")

    if not is_within_edit_window(tx["created_at"]):
        raise ConflictError("Edit window expired")

    delta = delta_for_delete(tx["type"], tx["amount"])
    await apply_account_delta(db=db, account_id=tx["account_id"], delta=delta)

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

    stamp = now.strftime("%Y%m%d%H%M%S%f")
    await upsert_notification(
        user_id=user_oid,
        **tx_deleted_payload(
            transaction_id=transaction_id,
            stamp=stamp,
            amount=tx.get("amount", 0),
        ),
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
        raise ConflictError("Transaction not deleted")

    if not can_restore_today(tx["deleted_at"]):
        raise ConflictError("Restore window expired")

    delta = delta_for_tx(tx["type"], tx["amount"])
    await apply_account_delta(db=db, account_id=tx["account_id"], delta=delta)

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

    stamp = now.strftime("%Y%m%d%H%M%S%f")
    await upsert_notification(
        user_id=user_oid,
        **tx_restored_payload(
            transaction_id=transaction_id,
            stamp=stamp,
            amount=tx.get("amount", 0),
        ),
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

    new_amount = round_money(new_amount)
    if new_amount <= 0:
        raise ValidationError("Amount must be positive")

    tx = await db.transactions.find_one(
        {"_id": tx_oid, "user_id": user_oid, "deleted_at": None}
    )
    if not tx:
        raise NotFoundError("Transaction not found")
    if tx.get("is_failed"):
        raise ConflictError("Failed transactions cannot be edited")

    if not is_within_edit_window(tx["created_at"]):
        raise ConflictError("Edit window expired")

    old_amount = tx["amount"]
    delta = delta_for_edit(tx["type"], old_amount, new_amount)
    await apply_account_delta(db=db, account_id=tx["account_id"], delta=delta)

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

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    await upsert_notification(
        user_id=user_oid,
        **tx_updated_payload(
            transaction_id=transaction_id,
            stamp=stamp,
            new_amount=new_amount,
        ),
    )


async def retry_failed_recurring_transaction(
    *,
    user_id: str,
    failed_transaction_id: str,
    request=None,
) -> bool:
    user_oid = ObjectId(user_id)
    failed_oid = ObjectId(failed_transaction_id)
    now = datetime.now(UTC)

    failed_tx = await db.transactions.find_one(
        {
            "_id": failed_oid,
            "user_id": user_oid,
            "deleted_at": None,
            "is_failed": True,
        }
    )
    if not failed_tx:
        raise NotFoundError("Failed recurring transaction not found")

    retry_status = failed_tx.get("retry_status", "pending")
    if retry_status == "resolved":
        return True

    account = await db.accounts.find_one(
        {"_id": failed_tx["account_id"], "user_id": user_oid, "deleted_at": None},
        {"balance": 1, "name": 1},
    )
    if not account:
        raise NotFoundError("Account not found")

    amount = failed_tx.get("amount", 0)
    tx_type = failed_tx.get("type")
    source = failed_tx.get("source", "")
    if is_retry_insufficient_funds(
        tx_type=tx_type,
        balance=account.get("balance", 0),
        amount=amount,
    ):
        await db.transactions.update_one(
            {"_id": failed_oid},
            build_retry_pending_update(now=now),
        )
        await upsert_notification(
            user_id=user_oid,
            **retry_failed_payload(
                failed_id=str(failed_oid),
                account_name=account.get("name", "Account"),
                balance=account.get("balance", 0),
                amount=amount,
            ),
        )
        return False

    existing_success = await db.transactions.find_one(
        {
            "user_id": user_oid,
            "retry_of": failed_oid,
            "deleted_at": None,
            "is_failed": {"$ne": True},
        },
        {"_id": 1},
    )
    if existing_success:
        await db.transactions.update_one(
            {"_id": failed_oid},
            build_retry_resolved_update(
                now=now,
                retry_transaction_id=existing_success["_id"],
            ),
        )
        return True

    retry_reference = None
    if source == "recurring":
        recurring_id = failed_tx.get("recurring_id")
        scheduled_for = failed_tx.get("scheduled_for")
        if not recurring_id or not scheduled_for:
            raise ConflictError("Failed transaction is missing recurring context")
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=UTC)

        recurring_rule = await db.recurring_deposits.find_one(
            {"_id": recurring_id, "user_id": user_oid}
        )
        if not recurring_rule:
            raise NotFoundError("Recurring rule not found for retry")

        success_tx = build_single_transaction_doc(
            user_id=failed_tx["user_id"],
            account_id=failed_tx["account_id"],
            tx_type=effective_tx_type,
            mode=failed_tx.get("mode", "online"),
            amount=amount,
            description=failed_tx.get("description", ""),
            category=failed_tx.get("category"),
            subcategory=failed_tx.get("subcategory"),
            created_at=now,
            source="recurring_retry",
            recurring_id=recurring_id,
            scheduled_for=scheduled_for,
            retry_of=failed_oid,
        )
        insert_result = await db.transactions.insert_one(success_tx)
        retry_reference = insert_result.inserted_id

        delta = delta_for_tx(tx_type, amount)
        await apply_account_delta(db=db, account_id=failed_tx["account_id"], delta=delta)

        next_run = calculate_next_run(
            last_run=scheduled_for.date(),
            start_date=recurring_rule["start_date"].date(),
            frequency=recurring_rule["frequency"],
        )
        await db.recurring_deposits.update_one(
            {"_id": recurring_id},
            {
                "$set": {
                    "last_run": scheduled_for,
                    "next_run": next_run,
                }
            },
        )
    elif tx_type == "transfer_out":
        target_account_id = failed_tx.get("target_account_id")
        if not target_account_id:
            raise ConflictError("Target account missing for failed transfer")
        target_account = await db.accounts.find_one(
            {"_id": target_account_id, "user_id": user_oid, "deleted_at": None},
            {"_id": 1},
        )
        if not target_account:
            raise NotFoundError("Target account not found for retry")

        transfer_id = ObjectId()
        await db.transactions.insert_many(
            build_transfer_transaction_docs(
                transfer_id=transfer_id,
                user_id=failed_tx["user_id"],
                source_account_id=failed_tx["account_id"],
                target_account_id=target_account_id,
                mode=failed_tx.get("mode", "online"),
                amount=amount,
                description=failed_tx.get("description", ""),
                category=failed_tx.get("category"),
                subcategory=failed_tx.get("subcategory"),
                created_at=now,
                source="manual_transfer_retry",
                retry_of=failed_oid,
            )
        )
        await apply_transfer_deltas(
            db=db,
            source_account_id=failed_tx["account_id"],
            target_account_id=target_account_id,
            amount=amount,
        )
        retry_reference = transfer_id
    else:
        success_tx = build_single_transaction_doc(
            user_id=failed_tx["user_id"],
            account_id=failed_tx["account_id"],
            tx_type=effective_tx_type,
            mode=failed_tx.get("mode", "online"),
            amount=amount,
            description=failed_tx.get("description", ""),
            category=failed_tx.get("category"),
            subcategory=failed_tx.get("subcategory"),
            created_at=now,
            source="manual_retry",
            retry_of=failed_oid,
        )
        insert_result = await db.transactions.insert_one(success_tx)
        retry_reference = insert_result.inserted_id
        delta = delta_for_tx(tx_type, amount)
        await apply_account_delta(db=db, account_id=failed_tx["account_id"], delta=delta)

    await db.transactions.update_one(
        {"_id": failed_oid},
        build_retry_resolved_update(
            now=now,
            retry_transaction_id=retry_reference,
        ),
    )

    await upsert_notification(
        user_id=user_oid,
        **retry_success_payload(
            failed_id=str(failed_oid),
            description=failed_tx.get("description", "Transaction"),
            amount=amount,
        ),
    )

    await audit_log(
        action="RECURRING_RETRY_SUCCESS",
        request=request,
        user={"user_id": user_id},
        meta={
            "failed_transaction_id": failed_transaction_id,
            "retry_transaction_id": str(retry_reference),
        },
    )
    return True

__all__ = [
    "create_transaction",
    "get_user_transactions",
    "delete_transaction",
    "restore_transaction",
    "edit_transaction",
    "retry_failed_recurring_transaction",
]
