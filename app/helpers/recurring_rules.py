from datetime import datetime, time, timezone

from app.helpers.recurring_schedule import (
    SKIP_MISSED_OCCURRENCES,
    calculate_next_occurrence,
)


def to_utc(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def recurring_status_of(rule: dict, now: datetime) -> str:
    ended_at = to_utc(rule.get("ended_at"))
    end_date = to_utc(rule.get("end_date"))
    if ended_at:
        return "ended"
    if end_date and end_date < now:
        return "ended"
    if rule.get("is_active", True):
        return "active"
    return "paused"


def compute_next_run_from_now(*, rule: dict, frequency: str, now: datetime) -> datetime:
    start_date = to_utc(rule.get("start_date"))
    if not start_date:
        raise Exception("Recurring rule is missing start date")

    candidate = calculate_next_occurrence(
        start_date=start_date.date(),
        frequency=frequency,
        today=now.date(),
        include_today=False,
        skip_missed=SKIP_MISSED_OCCURRENCES,
    )
    return to_utc(candidate)


def serialize_recurring_rule(*, rule: dict, account: dict, now: datetime) -> dict:
    return {
        "id": str(rule["_id"]),
        "account_id": str(rule.get("account_id")),
        "account_name": (account or {}).get("name", "Account"),
        "bank_name": (account or {}).get("bank_name", ""),
        "type": rule.get("type"),
        "mode": rule.get("mode"),
        "amount": rule.get("amount", 0),
        "description": rule.get("description", ""),
        "category": rule.get("category", {}),
        "subcategory": rule.get("subcategory", {}),
        "frequency": rule.get("frequency"),
        "interval": rule.get("interval", 1),
        "start_date": to_utc(rule.get("start_date")),
        "end_date": to_utc(rule.get("end_date")),
        "next_run": to_utc(rule.get("next_run")),
        "last_run": to_utc(rule.get("last_run")),
        "is_active": rule.get("is_active", True),
        "ended_at": to_utc(rule.get("ended_at")),
        "created_at": to_utc(rule.get("created_at")),
        "status": recurring_status_of(rule, now),
    }


def status_query(*, user_id, status: str, now: datetime) -> dict:
    query: dict = {"user_id": user_id}
    if status == "active":
        query.update(
            {
                "is_active": True,
                "$or": [{"end_date": None}, {"end_date": {"$gte": now}}],
                "ended_at": None,
            }
        )
    elif status == "paused":
        query.update(
            {
                "is_active": False,
                "ended_at": None,
                "$or": [{"end_date": None}, {"end_date": {"$gte": now}}],
            }
        )
    elif status == "ended":
        query.update({"$or": [{"ended_at": {"$ne": None}}, {"end_date": {"$lt": now}}]})
    return query
