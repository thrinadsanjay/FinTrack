import re
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.core.guards import RESTORE_WINDOW_HOURS


def build_transactions_query(
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
) -> dict:
    user_oid = ObjectId(user_id)
    now = datetime.now(timezone.utc)

    query: dict = {
        "user_id": user_oid,
        "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$gte": now - timedelta(hours=RESTORE_WINDOW_HOURS)}},
        ],
        "$and": [
            {
                "$or": [
                    {"is_failed": {"$ne": True}},
                    {"retry_status": {"$ne": "resolved"}},
                ]
            }
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
        created_at_filter: dict = {}
        if date_from:
            created_at_filter["$gte"] = datetime.fromisoformat(date_from).replace(
                tzinfo=timezone.utc
            )
        if date_to:
            created_at_filter["$lte"] = datetime.fromisoformat(date_to).replace(
                tzinfo=timezone.utc
            )
        query["created_at"] = created_at_filter

    return query


def resolve_transactions_sort(sort_by: str | None, sort_dir: str | None) -> tuple[str, int]:
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
    return sort_field, direction
