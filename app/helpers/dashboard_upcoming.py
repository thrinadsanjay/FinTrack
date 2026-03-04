from datetime import timezone, timedelta
from bson import ObjectId

from app.db.mongo import db
from app.helpers.dashboard_time import start_of_today_utc, next_month_start


async def fetch_upcoming_bills(uid: ObjectId, account_map: dict) -> tuple[list[dict], list[dict], dict]:
    today_start = start_of_today_utc()
    now = today_start
    tomorrow_start = today_start + timedelta(days=1)
    next_month = next_month_start(today_start)
    next_7_end = today_start + timedelta(days=7)

    recurring_cursor = db.recurring_deposits.find(
        {
            "user_id": uid,
            "is_active": True,
            "ended_at": None,
            "$or": [
                {"end_date": None},
                {"end_date": {"$gte": now}},
            ],
            "next_run": {"$gte": today_start, "$lt": next_month},
        }
    ).sort("next_run", 1)

    upcoming_bills_7 = []
    upcoming_bills_month = []
    required_by_account = {}

    async for bill in recurring_cursor:
        account_id = str(bill.get("account_id"))
        account_info = account_map.get(account_id, {})
        due_at = bill.get("next_run")
        if due_at and due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        item = {
            "id": str(bill.get("_id")),
            "account_id": account_id,
            "account_name": account_info.get("name", "Account"),
            "amount": bill.get("amount", 0),
            "type": bill.get("type"),
            "description": bill.get("description", "Recurring payment"),
            "frequency": bill.get("frequency"),
            "due_at": due_at,
        }

        if item["due_at"] and tomorrow_start <= item["due_at"] < next_month:
            upcoming_bills_month.append(item)
        if item["due_at"] and today_start <= item["due_at"] < next_7_end:
            upcoming_bills_7.append(item)

        if item["type"] == "debit":
            required_by_account[account_id] = required_by_account.get(account_id, 0) + item["amount"]

    return upcoming_bills_7, upcoming_bills_month, required_by_account
