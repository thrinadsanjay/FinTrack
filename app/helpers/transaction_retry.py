from datetime import datetime


def is_retry_insufficient_funds(*, tx_type: str | None, balance: float, amount: float) -> bool:
    return tx_type in {"debit", "transfer_out"} and balance < amount


def build_retry_pending_update(*, now: datetime) -> dict:
    return {"$set": {"retry_status": "pending", "last_retry_at": now}}


def build_retry_resolved_update(*, now: datetime, retry_transaction_id) -> dict:
    return {
        "$set": {
            "retry_status": "resolved",
            "resolved_at": now,
            "last_retry_at": now,
            "retry_transaction_id": retry_transaction_id,
        }
    }
