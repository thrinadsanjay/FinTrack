from datetime import datetime

from bson import ObjectId


def build_single_transaction_doc(
    *,
    user_id: ObjectId,
    account_id: ObjectId,
    tx_type: str,
    mode: str,
    amount: float,
    description: str,
    category: dict,
    subcategory: dict,
    created_at: datetime,
    source: str | None = None,
    retry_of: ObjectId | None = None,
    recurring_id: ObjectId | None = None,
    scheduled_for: datetime | None = None,
) -> dict:
    doc = {
        "user_id": user_id,
        "account_id": account_id,
        "type": tx_type,
        "mode": mode,
        "amount": amount,
        "description": description,
        "category": category,
        "subcategory": subcategory,
        "created_at": created_at,
        "deleted_at": None,
    }
    if source:
        doc["source"] = source
    if retry_of:
        doc["retry_of"] = retry_of
    if recurring_id:
        doc["recurring_id"] = recurring_id
    if scheduled_for:
        doc["scheduled_for"] = scheduled_for
    return doc


def build_failed_transaction_doc(
    *,
    user_id: ObjectId,
    account_id: ObjectId,
    tx_type: str,
    mode: str,
    amount: float,
    description: str,
    category: dict,
    subcategory: dict,
    source: str,
    failure_reason: str,
    created_at: datetime,
    target_account_id: ObjectId | None = None,
) -> dict:
    doc = {
        "user_id": user_id,
        "account_id": account_id,
        "type": tx_type,
        "mode": mode,
        "amount": amount,
        "description": description,
        "category": category,
        "subcategory": subcategory,
        "created_at": created_at,
        "deleted_at": None,
        "source": source,
        "is_failed": True,
        "failure_reason": failure_reason,
        "retry_status": "pending",
    }
    if target_account_id:
        doc["target_account_id"] = target_account_id
        doc["transfer_id"] = ObjectId()
    return doc


def build_transfer_transaction_docs(
    *,
    transfer_id: ObjectId,
    user_id: ObjectId,
    source_account_id: ObjectId,
    target_account_id: ObjectId,
    mode: str,
    amount: float,
    description: str,
    category: dict,
    subcategory: dict,
    created_at: datetime,
    source: str | None = None,
    retry_of: ObjectId | None = None,
) -> list[dict]:
    out_doc = {
        "transfer_id": transfer_id,
        "user_id": user_id,
        "account_id": source_account_id,
        "type": "transfer_out",
        "mode": mode,
        "amount": amount,
        "description": description,
        "category": category,
        "subcategory": subcategory,
        "created_at": created_at,
        "deleted_at": None,
    }
    in_doc = {
        "transfer_id": transfer_id,
        "user_id": user_id,
        "account_id": target_account_id,
        "type": "transfer_in",
        "mode": mode,
        "amount": amount,
        "description": description,
        "category": category,
        "subcategory": subcategory,
        "created_at": created_at,
        "deleted_at": None,
    }
    if source:
        out_doc["source"] = source
        in_doc["source"] = source
    if retry_of:
        out_doc["retry_of"] = retry_of
        in_doc["retry_of"] = retry_of
    return [out_doc, in_doc]
