from datetime import date, datetime, timezone, timedelta
from bson import ObjectId

from app.db.mongo import db
from app.helpers.recurring_schedule import VALID_FREQUENCIES, calculate_next_run


def _start_of_today_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def _start_of_month_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _next_month_start(dt: datetime) -> datetime:
    return datetime(
        dt.year + (1 if dt.month == 12 else 0),
        1 if dt.month == 12 else dt.month + 1,
        1,
        tzinfo=timezone.utc,
    )


def _as_utc(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _recurring_rule_item(rule: dict, account_map: dict) -> dict:
    account_id = str(rule.get("account_id"))
    account = account_map.get(account_id, {})
    due_at = _as_utc(rule.get("next_run"))
    tx_type = rule.get("type", "")
    amount = rule.get("amount", 0)
    balance = account.get("balance", 0)
    status = "scheduled"

    if tx_type == "debit" and balance < amount:
        status = "risk"

    return {
        "id": str(rule.get("_id")),
        "recurring_id": str(rule.get("_id")),
        "account_id": account_id,
        "description": rule.get("description", "Recurring transaction"),
        "account_name": account.get("name", "Account"),
        "amount": amount,
        "type": tx_type,
        "due_at": due_at,
        "next_payment_at": due_at,
        "frequency": rule.get("frequency", ""),
        "status": status,
    }


def _recurring_tx_item(
    tx: dict,
    account_map: dict,
    *,
    status: str | None = None,
    recurring_meta: dict | None = None,
) -> dict:
    account_name = account_map.get(str(tx.get("account_id")), {}).get("name", "Account")
    scheduled_for = _as_utc(tx.get("scheduled_for"))
    created_at = _as_utc(tx.get("created_at"))
    resolved_status = status
    if not resolved_status:
        resolved_status = "failed" if tx.get("is_failed") else "completed"

    return {
        "id": str(tx.get("_id")),
        "recurring_id": str(tx.get("recurring_id")) if tx.get("recurring_id") else None,
        "description": tx.get("description", "Recurring transaction"),
        "account_name": account_name,
        "amount": tx.get("amount", 0),
        "type": tx.get("type", ""),
        "due_at": scheduled_for or created_at,
        "next_payment_at": recurring_meta.get("next_run") if recurring_meta else None,
        "frequency": recurring_meta.get("frequency", "") if recurring_meta else "",
        "status": resolved_status,
        "retry_status": tx.get("retry_status"),
    }


def _merge_high_frequency_rows(items: list[dict]) -> list[dict]:
    merged: list[dict] = []
    grouped: dict[str, dict] = {}
    for item in items:
        recurring_id = item.get("recurring_id")
        frequency = (item.get("frequency") or "").lower()
        should_group = recurring_id and frequency in {"daily", "weekly", "biweekly"}
        if not should_group:
            merged.append(item)
            continue

        existing = grouped.get(recurring_id)
        if not existing:
            grouped[recurring_id] = item
            continue

        existing_due = existing.get("due_at")
        current_due = item.get("due_at")
        if current_due and (not existing_due or current_due > existing_due):
            grouped[recurring_id] = item

    merged.extend(grouped.values())
    merged.sort(key=lambda x: x.get("due_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return merged


def _group_recurring_items_by_date(items: list[dict], *, reverse: bool = False) -> list[dict]:
    grouped: dict[str, dict] = {}
    for item in items:
        due_at = _as_utc(item.get("due_at")) or _as_utc(item.get("next_payment_at"))
        if due_at:
            key = due_at.date().isoformat()
            label = due_at.strftime("%d %b %Y")
            sort_date = due_at.date()
        else:
            key = "undated"
            label = "No date"
            sort_date = None

        if key not in grouped:
            grouped[key] = {
                "date_key": key,
                "date_label": label,
                "date_sort": sort_date,
                "total": 0,
                "items": [],
            }

        grouped[key]["items"].append(item)
        grouped[key]["total"] += item.get("amount", 0) or 0

    groups = list(grouped.values())
    groups.sort(
        key=lambda g: g.get("date_sort") or date.min,
        reverse=reverse,
    )
    return groups


def _recurring_item_key(item: dict) -> str:
    recurring_id = item.get("recurring_id")
    if recurring_id:
        return f"rid:{recurring_id}"
    return (
        f"raw:{item.get('description','')}:"
        f"{item.get('account_name','')}:"
        f"{item.get('amount',0)}"
    )


def _expand_rule_occurrences(
    *,
    rule: dict,
    window_start_inclusive: datetime,
    account_map: dict,
    window_end_exclusive: datetime,
) -> list[dict]:
    next_run = _as_utc(rule.get("next_run"))
    if not next_run:
        return []

    frequency = (rule.get("frequency") or "").lower()
    if frequency not in VALID_FREQUENCIES:
        return [_recurring_rule_item(rule, account_map)]

    start_anchor = _as_utc(rule.get("start_date")) or next_run
    end_date = _as_utc(rule.get("end_date"))
    occurrences: list[dict] = []
    current_due = next_run
    guard = 0

    while guard < 500 and current_due < window_end_exclusive:
        if (
            current_due >= window_start_inclusive
            and (not end_date or current_due <= end_date)
        ):
            item = _recurring_rule_item(rule, account_map)
            item["due_at"] = current_due
            item["next_payment_at"] = current_due
            occurrences.append(item)

        nxt = calculate_next_run(
            last_run=current_due.date(),
            start_date=start_anchor.date(),
            frequency=frequency,
        )
        current_due = _as_utc(nxt)
        guard += 1

    return occurrences


def _project_rule_amount_until_month_end(
    *,
    rule: dict,
    from_dt: datetime,
    month_end_exclusive: datetime,
) -> float:
    frequency = (rule.get("frequency") or "").lower()
    if frequency not in VALID_FREQUENCIES:
        return 0

    amount = rule.get("amount", 0) or 0
    if amount <= 0:
        return 0

    next_run = _as_utc(rule.get("next_run"))
    if not next_run:
        return 0

    end_date = _as_utc(rule.get("end_date"))
    start_date = _as_utc(rule.get("start_date"))
    anchor_start_date = (start_date or next_run).date()

    projected_total = 0.0
    current = next_run
    guard = 0
    while guard < 1000 and current and current < month_end_exclusive:
        if current >= from_dt and (not end_date or current <= end_date):
            projected_total += amount

        nxt = calculate_next_run(
            last_run=current.date(),
            start_date=anchor_start_date,
            frequency=frequency,
        )
        current = _as_utc(nxt)
        guard += 1

    return projected_total


async def fetch_dashboard_recurring_overview(uid: ObjectId, account_map: dict) -> dict:
    now = datetime.now(timezone.utc)
    today_start = _start_of_today_utc()
    tomorrow_start = today_start + timedelta(days=1)
    day_after_tomorrow_start = today_start + timedelta(days=2)
    next_month_start = _next_month_start(today_start)
    month_start = _start_of_month_utc()

    recurring_source_match = {"$in": ["recurring", "recurring_retry"]}
    recurring_rule_meta = {}
    recurring_meta_cursor = db.recurring_deposits.find(
        {"user_id": uid},
        {"frequency": 1, "next_run": 1},
    )
    async for rule in recurring_meta_cursor:
        recurring_rule_meta[str(rule.get("_id"))] = {
            "frequency": rule.get("frequency", ""),
            "next_run": _as_utc(rule.get("next_run")),
        }

    today_cursor = (
        db.transactions
        .find(
            {
                "user_id": uid,
                "deleted_at": None,
                "source": recurring_source_match,
                "scheduled_for": {"$gte": today_start, "$lt": tomorrow_start},
            }
        )
        .sort("scheduled_for", 1)
        .limit(8)
    )

    tomorrow_rules_cursor = (
        db.recurring_deposits
        .find(
            {
                "user_id": uid,
                "is_active": True,
                "ended_at": None,
                "$or": [
                    {"end_date": None},
                    {"end_date": {"$gte": tomorrow_start}},
                ],
                "next_run": {"$gte": tomorrow_start, "$lt": day_after_tomorrow_start},
            }
        )
        .sort("next_run", 1)
        .limit(8)
    )

    completed_month_cursor = (
        db.transactions
        .find(
            {
                "user_id": uid,
                "deleted_at": None,
                "source": recurring_source_match,
                "is_failed": {"$ne": True},
                "scheduled_for": {"$gte": month_start, "$lt": next_month_start},
            }
        )
        .sort("scheduled_for", -1)
        .limit(12)
    )

    upcoming_month_cursor = (
        db.recurring_deposits
        .find(
            {
                "user_id": uid,
                "is_active": True,
                "ended_at": None,
                "$or": [
                    {"end_date": None},
                    {"end_date": {"$gte": tomorrow_start}},
                ],
                "next_run": {"$gte": tomorrow_start, "$lt": next_month_start},
            }
        )
        .sort("next_run", 1)
        .limit(60)
    )

    projection_rules_cursor = db.recurring_deposits.find(
        {
            "user_id": uid,
            "is_active": True,
            "ended_at": None,
            "$or": [
                {"end_date": None},
                {"end_date": {"$gte": today_start}},
            ],
            "next_run": {"$lt": next_month_start},
        },
        {
            "frequency": 1,
            "amount": 1,
            "next_run": 1,
            "start_date": 1,
            "end_date": 1,
        },
    )

    failed_month_cursor = (
        db.transactions
        .find(
            {
                "user_id": uid,
                "deleted_at": None,
                "source": recurring_source_match,
                "is_failed": True,
                "scheduled_for": {"$gte": month_start, "$lt": next_month_start},
            }
        )
        .sort("scheduled_for", -1)
        .limit(20)
    )

    paid_this_month_total_cursor = db.transactions.aggregate(
        [
            {
                "$match": {
                    "user_id": uid,
                    "deleted_at": None,
                    "source": recurring_source_match,
                    "is_failed": {"$ne": True},
                    "scheduled_for": {"$gte": month_start, "$lt": next_month_start},
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": "$amount"},
                }
            },
        ]
    )

    today = []
    today_recurring_ids = set()
    async for tx in today_cursor:
        if tx.get("is_failed") and tx.get("retry_status") == "resolved":
            continue
        recurring_meta = recurring_rule_meta.get(str(tx.get("recurring_id")), {})
        today.append(_recurring_tx_item(tx, account_map, recurring_meta=recurring_meta))
        recurring_id = tx.get("recurring_id")
        if recurring_id:
            today_recurring_ids.add(str(recurring_id))

    tomorrow = []
    async for rule in tomorrow_rules_cursor:
        rule_id = str(rule.get("_id"))
        if rule_id in today_recurring_ids:
            continue
        tomorrow.append(_recurring_rule_item(rule, account_map))

    completed_month = []
    async for tx in completed_month_cursor:
        recurring_meta = recurring_rule_meta.get(str(tx.get("recurring_id")), {})
        completed_month.append(
            _recurring_tx_item(
                tx,
                account_map,
                status="completed",
                recurring_meta=recurring_meta,
            )
        )

    upcoming_rules = []
    async for rule in upcoming_month_cursor:
        upcoming_rules.append(rule)

    projection_rules = []
    async for rule in projection_rules_cursor:
        projection_rules.append(rule)

    projected_balance_by_account = {
        account_id: info.get("balance", 0)
        for account_id, info in account_map.items()
    }

    expanded_upcoming = []
    for rule in upcoming_rules:
        expanded_upcoming.extend(
            _expand_rule_occurrences(
                rule=rule,
                window_start_inclusive=day_after_tomorrow_start,
                account_map=account_map,
                window_end_exclusive=next_month_start,
            )
        )

    expanded_upcoming.sort(
        key=lambda item: _as_utc(item.get("due_at")) or datetime.max.replace(tzinfo=timezone.utc)
    )

    upcoming_month = []
    for item in expanded_upcoming:
        account_id = str(item.get("account_id") or "")
        amount = item.get("amount", 0)
        tx_type = item.get("type")
        current_balance = projected_balance_by_account.get(
            account_id,
            account_map.get(account_id, {}).get("balance", 0),
        )

        if tx_type == "debit":
            if current_balance < amount:
                item["status"] = "critical"
            else:
                item["status"] = "upcoming"
            projected_balance_by_account[account_id] = current_balance - amount
        else:
            item["status"] = "upcoming"
            if tx_type == "credit":
                projected_balance_by_account[account_id] = current_balance + amount

        upcoming_month.append(item)

    failed_month = []
    async for tx in failed_month_cursor:
        if tx.get("retry_status") == "resolved":
            continue
        recurring_meta = recurring_rule_meta.get(str(tx.get("recurring_id")), {})
        failed_month.append(
            _recurring_tx_item(
                tx,
                account_map,
                status="failed",
                recurring_meta=recurring_meta,
            )
        )

    paid_this_month_total_all = 0.0
    async for row in paid_this_month_total_cursor:
        paid_this_month_total_all = row.get("total", 0) or 0

    completed_month = _merge_high_frequency_rows(completed_month)
    failed_month = _merge_high_frequency_rows(failed_month)

    daily_candidates = [
        *today,
        *tomorrow,
        *upcoming_month,
        *completed_month,
        *failed_month,
    ]
    daily_index: dict[str, dict] = {}
    for item in daily_candidates:
        if (item.get("frequency") or "").lower() != "daily":
            continue
        key = _recurring_item_key(item)
        existing = daily_index.get(key)
        current_due = _as_utc(item.get("due_at")) or _as_utc(item.get("next_payment_at"))
        if not existing:
            daily_index[key] = item
            continue
        existing_due = _as_utc(existing.get("due_at")) or _as_utc(existing.get("next_payment_at"))
        if current_due and (not existing_due or current_due > existing_due):
            daily_index[key] = item

    daily_items = list(daily_index.values())
    daily_items.sort(
        key=lambda item: _as_utc(item.get("due_at")) or _as_utc(item.get("next_payment_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=False,
    )
    daily_total = sum(item.get("amount", 0) or 0 for item in daily_items)

    upcoming_month_non_daily = [
        item for item in upcoming_month
        if (item.get("frequency") or "").lower() != "daily"
    ]

    today_total = sum(item.get("amount", 0) or 0 for item in today)
    tomorrow_total = sum(item.get("amount", 0) or 0 for item in tomorrow)
    upcoming_total = sum(item.get("amount", 0) or 0 for item in upcoming_month_non_daily)
    paid_this_month_total = paid_this_month_total_all
    processed_items = sorted(
        [*completed_month, *failed_month],
        key=lambda item: item.get("due_at") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    processed_total = sum(item.get("amount", 0) or 0 for item in processed_items)
    projected_remaining_this_month = 0.0
    projected_daily_remaining_this_month = 0.0
    for rule in projection_rules:
        projected_value = _project_rule_amount_until_month_end(
            rule=rule,
            from_dt=today_start,
            month_end_exclusive=next_month_start,
        )
        projected_remaining_this_month += projected_value
        if (rule.get("frequency") or "").lower() == "daily":
            projected_daily_remaining_this_month += projected_value

    total_scheduled_amount = paid_this_month_total + projected_remaining_this_month
    remaining_amount = max(projected_remaining_this_month, 0)
    paid_progress_percent = (
        round((paid_this_month_total / total_scheduled_amount) * 100, 1)
        if total_scheduled_amount > 0
        else 0
    )
    next_due_dt = None
    if tomorrow:
        next_due_dt = tomorrow[0].get("due_at")
    elif upcoming_month_non_daily:
        next_due_dt = upcoming_month_non_daily[0].get("due_at")

    upcoming_groups = _group_recurring_items_by_date(upcoming_month_non_daily)
    processed_groups = _group_recurring_items_by_date(processed_items, reverse=True)

    failed_month_count = await db.transactions.count_documents(
        {
            "user_id": uid,
            "deleted_at": None,
            "source": recurring_source_match,
            "is_failed": True,
            "retry_status": {"$ne": "resolved"},
            "scheduled_for": {"$gte": month_start, "$lt": next_month_start},
        }
    )

    return {
        "today": today,
        "today_total": today_total,
        "tomorrow": tomorrow,
        "tomorrow_total": tomorrow_total,
        "daily_items": daily_items,
        "daily_total": daily_total,
        "daily_projected_total": projected_daily_remaining_this_month,
        "completed_month": completed_month,
        "upcoming_month": upcoming_month_non_daily,
        "upcoming_total": upcoming_total,
        "upcoming_count": len(upcoming_month_non_daily),
        "upcoming_groups": upcoming_groups,
        "failed_month": failed_month,
        "processed_total": processed_total,
        "processed_groups": processed_groups,
        "paid_this_month_total": paid_this_month_total,
        "remaining_amount": remaining_amount,
        "total_scheduled_amount": total_scheduled_amount,
        "paid_progress_percent": paid_progress_percent,
        "next_due_label": next_due_dt.strftime("%d %b %Y") if next_due_dt else None,
        "failed_month_count": failed_month_count,
        "has_failures": failed_month_count > 0,
        "generated_at": now,
    }
