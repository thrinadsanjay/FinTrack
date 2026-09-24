import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bson import ObjectId

from app.core.guards import RESTORE_WINDOW_HOURS
from app.core.time import DEFAULT_TZ

APP_ZONE = ZoneInfo(DEFAULT_TZ)


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
    account_ids_for_search: list | None = None,
    tz: ZoneInfo | None = None,
) -> dict:
    user_oid = ObjectId(user_id)
    now = datetime.now(timezone.utc)
    zone = tz or APP_ZONE

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
        elif tx_type == "card_payment":
            query["type"] = {"$in": ["transfer_in", "transfer_out"]}
            query["source"] = "card_payment"
        else:
            query["type"] = tx_type

    if category_code:
        query["category.code"] = category_code
    if subcategory_code:
        query["subcategory.code"] = subcategory_code
    if amount is not None:
        query["amount"] = amount

    if search:
        search_or: list[dict] = [
            {"description": {"$regex": re.escape(search), "$options": "i"}},
        ]
        normalized = search.replace(",", "").strip()
        try:
            search_or.append({"amount": float(normalized)})
        except ValueError:
            pass
        if account_ids_for_search:
            search_or.append({"account_id": {"$in": list(account_ids_for_search)}})
        query["$and"].append({"$or": search_or})

    if date_from or date_to:
        created_at_filter: dict = {}
        if date_from:
            from app.core.time import parse_user_date

            start_day = parse_user_date(date_from)
            if start_day:
                local_start = datetime(
                    start_day.year, start_day.month, start_day.day, 0, 0, 0, 0, tzinfo=zone
                )
                created_at_filter["$gte"] = local_start.astimezone(timezone.utc)
        if date_to:
            from app.core.time import parse_user_date

            end_day = parse_user_date(date_to)
            if end_day:
                local_end = datetime(
                    end_day.year, end_day.month, end_day.day, 23, 59, 59, 999999, tzinfo=zone
                )
                created_at_filter["$lte"] = local_end.astimezone(timezone.utc)
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
