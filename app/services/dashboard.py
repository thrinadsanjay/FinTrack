"""
Dashboard read-only analytics.

Responsibilities:
- Compute balances
- Aggregate transaction stats
- Fetch recent activity

Must NOT:
- Render templates
- Write audit logs
"""

from datetime import datetime, timezone, timedelta
from bson import ObjectId
from app.db.mongo import db
from app.services.notifications import (
    upsert_notification,
    list_notifications,
)


# ======================================================
# TIME HELPERS (UTC)
# ======================================================

def start_of_today_utc():
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def start_of_month_utc():
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)

def start_of_day_utc(dt: datetime):
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


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

    # Warn when the scheduled debit may fail due to low funds.
    if tx_type == "debit" and balance < amount:
        status = "risk"

    return {
        "id": str(rule.get("_id")),
        "description": rule.get("description", "Recurring transaction"),
        "account_name": account.get("name", "Account"),
        "amount": amount,
        "type": tx_type,
        "due_at": due_at,
        "status": status,
    }


def _recurring_tx_item(tx: dict, account_map: dict, *, status: str | None = None) -> dict:
    account_name = account_map.get(str(tx.get("account_id")), {}).get("name", "Account")
    scheduled_for = _as_utc(tx.get("scheduled_for"))
    created_at = _as_utc(tx.get("created_at"))
    resolved_status = status
    if not resolved_status:
        resolved_status = "failed" if tx.get("is_failed") else "completed"

    return {
        "id": str(tx.get("_id")),
        "description": tx.get("description", "Recurring transaction"),
        "account_name": account_name,
        "amount": tx.get("amount", 0),
        "type": tx.get("type", ""),
        "due_at": scheduled_for or created_at,
        "status": resolved_status,
        "retry_status": tx.get("retry_status"),
    }


async def _fetch_recurring_overview(uid: ObjectId, account_map: dict):
    now = datetime.now(timezone.utc)
    today_start = start_of_today_utc()
    tomorrow_start = today_start + timedelta(days=1)
    day_after_tomorrow_start = today_start + timedelta(days=2)
    next_month_start = _next_month_start(today_start)
    month_start = start_of_month_utc()

    recurring_source_match = {"$in": ["recurring", "recurring_retry"]}

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
                    {"end_date": {"$gte": day_after_tomorrow_start}},
                ],
                "next_run": {"$gte": day_after_tomorrow_start, "$lt": next_month_start},
            }
        )
        .sort("next_run", 1)
        .limit(12)
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

    today = []
    today_recurring_ids = set()
    async for tx in today_cursor:
        # Once a failed recurring transaction is retried successfully,
        # hide the original failed row from dashboard buckets.
        if tx.get("is_failed") and tx.get("retry_status") == "resolved":
            continue
        today.append(_recurring_tx_item(tx, account_map))
        recurring_id = tx.get("recurring_id")
        if recurring_id:
            today_recurring_ids.add(str(recurring_id))

    tomorrow = []
    async for rule in tomorrow_rules_cursor:
        # Avoid showing the same recurring rule in both today and tomorrow buckets.
        rule_id = str(rule.get("_id"))
        if rule_id in today_recurring_ids:
            continue
        tomorrow.append(_recurring_rule_item(rule, account_map))

    completed_month = []
    async for tx in completed_month_cursor:
        completed_month.append(_recurring_tx_item(tx, account_map, status="completed"))

    upcoming_rules = []
    async for rule in upcoming_month_cursor:
        upcoming_rules.append(rule)

    # Date-ordered balance projection for upcoming monthly bills.
    # If a debit pushes projected balance below zero, mark that item critical.
    projected_balance_by_account = {
        account_id: info.get("balance", 0)
        for account_id, info in account_map.items()
    }

    upcoming_month = []
    for rule in upcoming_rules:
        account_id = str(rule.get("account_id"))
        amount = rule.get("amount", 0)
        tx_type = rule.get("type")
        item = _recurring_rule_item(rule, account_map)
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
        failed_month.append(_recurring_tx_item(tx, account_map, status="failed"))

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
        "tomorrow": tomorrow,
        "completed_month": completed_month,
        "upcoming_month": upcoming_month,
        "failed_month": failed_month,
        "failed_month_count": failed_month_count,
        "has_failures": failed_month_count > 0,
        "generated_at": now,
    }


async def _fetch_upcoming_bills(uid: ObjectId, account_map: dict):
    now = datetime.now(timezone.utc)
    today_start = start_of_today_utc()
    tomorrow_start = start_of_today_utc() + timedelta(days=1)
    next_month_start = _next_month_start(now)
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
            "next_run": {"$gte": today_start, "$lt": next_month_start},
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

        if item["due_at"] and tomorrow_start <= item["due_at"] < next_month_start:
            upcoming_bills_month.append(item)
        if item["due_at"] and today_start <= item["due_at"] < next_7_end:
            upcoming_bills_7.append(item)

        if item["type"] == "debit":
            required_by_account[account_id] = (
                required_by_account.get(account_id, 0) + item["amount"]
            )

    return upcoming_bills_7, upcoming_bills_month, required_by_account


# ======================================================
# DASHBOARD SUMMARY
# ======================================================

async def get_dashboard_summary(user_id: str):
    uid = ObjectId(user_id)

    # -----------------------------
    # TOTAL BALANCE (active accounts only)
    # -----------------------------
    balance_cursor = db.accounts.aggregate([
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$balance"},
            }
        },
    ])

    balance = 0
    async for row in balance_cursor:
        balance = row["total"]

    # -----------------------------
    # TODAY CREDIT / DEBIT
    # -----------------------------
    today = start_of_today_utc()

    today_cursor = db.transactions.aggregate([
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
                "is_failed": {"$ne": True},
                "created_at": {"$gte": today},
            }
        },
        {
            "$group": {
                "_id": "$type",  # credit | debit
                "total": {"$sum": "$amount"},
            }
        },
    ])

    today_credit = today_debit = 0
    async for row in today_cursor:
        if row["_id"] == "credit":
            today_credit = row["total"]
        elif row["_id"] == "debit":
            today_debit = row["total"]

    # -----------------------------
    # MONTH NET
    # -----------------------------
    month_start = start_of_month_utc()

    month_cursor = db.transactions.aggregate([
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
                "is_failed": {"$ne": True},
                "created_at": {"$gte": month_start},
            }
        },
        {
            "$group": {
                "_id": "$type",
                "total": {"$sum": "$amount"},
            }
        },
    ])

    month_credit = month_debit = 0
    async for row in month_cursor:
        if row["_id"] == "credit":
            month_credit = row["total"]
        elif row["_id"] == "debit":
            month_debit = row["total"]

    # -----------------------------
    # ACCOUNT BALANCES (ACTIVE)
    # -----------------------------
    accounts_cursor = (
        db.accounts
        .find(
            {"user_id": uid, "deleted_at": None},
            {"name": 1, "bank_name": 1, "balance": 1, "type": 1, "credit_limit": 1},
        )
        .sort("balance", -1)
    )
    account_balances = []
    account_map = {}
    async for acc in accounts_cursor:
        acc_id = str(acc["_id"])
        account_balances.append(
            {
                "id": acc_id,
                "name": acc.get("name"),
                "bank_name": acc.get("bank_name"),
                "balance": acc.get("balance", 0),
                "type": acc.get("type"),
                "credit_limit": acc.get("credit_limit"),
            }
        )
        account_map[acc_id] = {
            "name": acc.get("name"),
            "bank_name": acc.get("bank_name"),
            "balance": acc.get("balance", 0),
            "type": acc.get("type"),
            "credit_limit": acc.get("credit_limit"),
        }

    # -----------------------------
    # TOP SPENDING CATEGORIES (MONTH)
    # -----------------------------
    top_spending_categories = []
    if month_debit > 0:
        categories_cursor = db.transactions.aggregate([
            {
                "$match": {
                    "user_id": uid,
                    "deleted_at": None,
                    "is_failed": {"$ne": True},
                    "created_at": {"$gte": month_start},
                    "type": "debit",
                }
            },
            {
                "$group": {
                    "_id": {"$ifNull": ["$category.name", "Uncategorized"]},
                    "total": {"$sum": "$amount"},
                }
            },
            {"$sort": {"total": -1}},
            {"$limit": 5},
        ])

        async for row in categories_cursor:
            total = row.get("total", 0)
            percent = round((total / month_debit) * 100, 1) if month_debit else 0
            top_spending_categories.append(
                {
                    "name": row.get("_id") or "Uncategorized",
                    "total": total,
                    "percent": percent,
                }
            )

    # -----------------------------
    # LARGEST TRANSACTIONS (MONTH)
    # -----------------------------
    largest_transactions = []
    largest_cursor = (
        db.transactions
        .find(
            {
                "user_id": uid,
                "deleted_at": None,
                "is_failed": {"$ne": True},
                "created_at": {"$gte": month_start},
                "type": "debit",
                "amount": {"$gt": 10000},
            },
            {"description": 1, "amount": 1, "created_at": 1, "account_id": 1},
        )
        .sort("amount", -1)
        .limit(5)
    )
    async for tx in largest_cursor:
        account_name = account_map.get(str(tx.get("account_id")), {}).get("name", "Account")
        largest_transactions.append(
            {
                "description": tx.get("description", "Transaction"),
                "amount": tx.get("amount", 0),
                "created_at": tx.get("created_at"),
                "account_name": account_name,
            }
        )

    # -----------------------------
    # DAILY TREND (CURRENT MONTH)
    # -----------------------------
    today = datetime.now(timezone.utc)
    trend_start = start_of_month_utc()
    trend_end = start_of_day_utc(today) + timedelta(days=1)

    trend_cursor = db.transactions.aggregate([
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
                "is_failed": {"$ne": True},
                "created_at": {"$gte": trend_start, "$lt": trend_end},
                "type": {"$in": ["credit", "debit"]},
            }
        },
        {
            "$group": {
                "_id": {
                    "day": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$created_at",
                            "timezone": "UTC",
                        }
                    },
                    "type": "$type",
                },
                "total": {"$sum": "$amount"},
            }
        },
    ])

    daily_map = {}
    async for row in trend_cursor:
        day = row["_id"]["day"]
        tx_type = row["_id"]["type"]
        daily_map.setdefault(day, {"credit": 0, "debit": 0})
        daily_map[day][tx_type] = row["total"]

    trend_daily = []
    day_count = (start_of_day_utc(today) - trend_start).days + 1
    for i in range(day_count):
        day_dt = trend_start + timedelta(days=i)
        day_key = day_dt.strftime("%Y-%m-%d")
        credit = daily_map.get(day_key, {}).get("credit", 0)
        debit = daily_map.get(day_key, {}).get("debit", 0)
        trend_daily.append(
            {
                "date": day_key,
                "day": day_dt.day,
                "income": credit,
                "expense": debit,
            }
        )

    cashflow_month_label = trend_start.strftime("%b %Y")

    # -----------------------------
    # MONTHLY TREND (LAST 12 MONTHS)
    # -----------------------------
    month_anchor = start_of_month_utc()
    start_year = month_anchor.year
    start_month = month_anchor.month
    for _ in range(11):
        if start_month == 1:
            start_month = 12
            start_year -= 1
        else:
            start_month -= 1
    month_start = datetime(start_year, start_month, 1, tzinfo=timezone.utc)

    monthly_cursor = db.transactions.aggregate([
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
                "is_failed": {"$ne": True},
                "created_at": {"$gte": month_start},
                "type": {"$in": ["credit", "debit"]},
            }
        },
        {
            "$group": {
                "_id": {
                    "month": {
                        "$dateToString": {
                            "format": "%Y-%m",
                            "date": "$created_at",
                            "timezone": "UTC",
                        }
                    },
                    "type": "$type",
                },
                "total": {"$sum": "$amount"},
            }
        },
    ])

    monthly_map = {}
    async for row in monthly_cursor:
        month_key = row["_id"]["month"]
        tx_type = row["_id"]["type"]
        monthly_map.setdefault(month_key, {"credit": 0, "debit": 0})
        monthly_map[month_key][tx_type] = row["total"]

    trend_monthly = []
    current = month_start
    for _ in range(12):
        month_key = current.strftime("%Y-%m")
        credit = monthly_map.get(month_key, {}).get("credit", 0)
        debit = monthly_map.get(month_key, {}).get("debit", 0)
        trend_monthly.append(
            {
                "month": month_key,
                "month_short": current.strftime("%b"),
                "month_label": current.strftime("%b %Y"),
                "income": credit,
                "expense": debit,
                "net": credit - debit,
            }
        )
        next_month = (current.month % 12) + 1
        next_year = current.year + (1 if current.month == 12 else 0)
        current = datetime(next_year, next_month, 1, tzinfo=timezone.utc)

    monthly_range_label = ""
    monthly_till_label = month_anchor.strftime("%b %Y")
    if trend_monthly:
        monthly_range_label = (
            f"{trend_monthly[0]['month_label']} - {trend_monthly[-1]['month_label']}"
        )

    # -----------------------------
    # UPCOMING BILLS (NEXT 7 DAYS + TOMORROW TO MONTH END)
    # -----------------------------
    upcoming_bills_7, upcoming_bills_month, required_by_account = (
        await _fetch_upcoming_bills(uid, account_map)
    )
    recurring_overview = await _fetch_recurring_overview(uid, account_map)

    notifications = await _persist_notifications(
        uid=uid,
        required_by_account=required_by_account,
        account_map=account_map,
    )

    # -----------------------------
    # SAVINGS RATE (CURRENT + CHANGE VS PREV)
    # -----------------------------
    savings_rate = None
    if month_credit > 0:
        savings_rate = round(((month_credit - month_debit) / month_credit) * 100, 1)

    prev_month_anchor = month_start - timedelta(days=1)
    prev_month_key = prev_month_anchor.strftime("%Y-%m")
    prev_credit = monthly_map.get(prev_month_key, {}).get("credit", 0)
    prev_debit = monthly_map.get(prev_month_key, {}).get("debit", 0)
    savings_rate_change = None
    if savings_rate is not None and prev_credit > 0:
        prev_rate = ((prev_credit - prev_debit) / prev_credit) * 100
        savings_rate_change = round(savings_rate - prev_rate, 1)

    # -----------------------------
    # ACCOUNT ALERTS (NOTIFS + CC LIMIT)
    # -----------------------------
    account_alerts = [
        {
            "level": n.get("notif_type", "info"),
            "title": n.get("title", "Alert"),
            "message": n.get("message", ""),
        }
        for n in notifications
    ]

    for account in account_balances:
        if account.get("type") != "credit_card":
            continue
        credit_limit = account.get("credit_limit")
        if not credit_limit:
            continue
        balance_value = abs(account.get("balance", 0))
        if credit_limit <= 0:
            continue
        usage_ratio = balance_value / credit_limit
        if usage_ratio >= 0.8:
            usage_percent = round(usage_ratio * 100)
            account_alerts.append(
                {
                    "level": "warning",
                    "title": "Credit card nearing limit",
                    "message": (
                        f"{account.get('name', 'Credit card')} is at "
                        f"{usage_percent}% of its ₹ {credit_limit} limit."
                    ),
                }
            )

    return {
        "balance": balance,
        "today_credit": today_credit,
        "today_debit": today_debit,
        "today_income": today_credit,
        "today_expense": today_debit,
        "month_net": month_credit - month_debit,
        "month_income": month_credit,
        "month_expense": month_debit,
        "savings_rate": savings_rate,
        "savings_rate_change": savings_rate_change,
        "account_balances": account_balances,
        "top_spending_categories": top_spending_categories,
        "largest_transactions": largest_transactions,
        "trend_daily": trend_daily,
        "cashflow_month_label": cashflow_month_label,
        "trend_monthly": trend_monthly,
        "monthly_range_label": monthly_range_label,
        "monthly_till_label": monthly_till_label,
        "upcoming_bills_7": upcoming_bills_7,
        "upcoming_bills_month": upcoming_bills_month,
        "recurring_overview": recurring_overview,
        "notifications": notifications,
        "account_alerts": account_alerts,
    }


async def get_user_notifications(user_id: str):
    uid = ObjectId(user_id)
    accounts_cursor = (
        db.accounts
        .find(
            {"user_id": uid, "deleted_at": None},
            {"name": 1, "bank_name": 1, "balance": 1, "type": 1},
        )
    )
    account_map = {}
    async for acc in accounts_cursor:
        account_map[str(acc["_id"])] = {
            "name": acc.get("name"),
            "bank_name": acc.get("bank_name"),
            "balance": acc.get("balance", 0),
            "type": acc.get("type"),
        }

    _, _, required_by_account = await _fetch_upcoming_bills(uid, account_map)
    return await _persist_notifications(
        uid=uid,
        required_by_account=required_by_account,
        account_map=account_map,
    )


async def _persist_notifications(
    *,
    uid: ObjectId,
    required_by_account: dict,
    account_map: dict,
):
    active_low_balance_keys = set()

    for account_id, required in required_by_account.items():
        account_info = account_map.get(account_id, {})
        balance_value = account_info.get("balance", 0)
        if balance_value < required:
            key = f"low_balance:{account_id}"
            active_low_balance_keys.add(key)
            await upsert_notification(
                user_id=uid,
                key=key,
                notif_type="warning",
                title="Low balance for upcoming bills",
                message=(
                    f"{account_info.get('name', 'Account')} needs ₹ {required} "
                    f"for pending recurring bills this month, but has ₹ {balance_value}."
                ),
            )

    # Balance-threshold alerts.
    active_balance_threshold_keys = set()
    for account_id, account_info in account_map.items():
        if account_info.get("type") == "credit_card":
            continue
        balance_value = account_info.get("balance", 0)
        notif_type = None
        title = None
        if balance_value <= 500:
            notif_type = "critical"
            title = "Critical low balance"
        elif balance_value <= 1000:
            notif_type = "warning"
            title = "Low balance warning"

        if not notif_type:
            continue

        key = f"balance_threshold:{account_id}"
        active_balance_threshold_keys.add(key)
        await upsert_notification(
            user_id=uid,
            key=key,
            notif_type=notif_type,
            title=title,
            message=(
                f"{account_info.get('name', 'Account')} has ₹ {balance_value}. "
                "Try adding funds soon."
            ),
        )

    # Recurring transactions scheduled for today.
    today_start = start_of_today_utc()
    tomorrow_start = today_start + timedelta(days=1)
    recurring_today_cursor = db.recurring_deposits.find(
        {
            "user_id": uid,
            "is_active": True,
            "ended_at": None,
            "$and": [
                {
                    "$or": [
                        {"end_date": None},
                        {"end_date": {"$gte": today_start}},
                    ]
                },
                {
                    "$or": [
                        {"next_run": {"$gte": today_start, "$lt": tomorrow_start}},
                        {"last_run": {"$gte": today_start, "$lt": tomorrow_start}},
                    ]
                },
            ],
        }
    ).sort("next_run", 1)

    active_scheduled_today_keys = set()
    today_key = today_start.strftime("%Y-%m-%d")

    async for rule in recurring_today_cursor:
        rule_id = str(rule.get("_id"))
        account_id = str(rule.get("account_id"))
        account_name = account_map.get(account_id, {}).get("name", "Account")
        key = f"scheduled_today:{rule_id}:{today_key}"
        active_scheduled_today_keys.add(key)
        await upsert_notification(
            user_id=uid,
            key=key,
            notif_type="info",
            title="Payment due today",
            message=(
                f"{rule.get('description', 'Recurring transaction')} for ₹ {rule.get('amount', 0)} "
                f"is scheduled today in {account_name}."
            ),
        )

    # Clear stale low-balance warnings when there are no qualifying bills this month.
    stale_low_balance_query = {"user_id": uid, "key": {"$regex": r"^low_balance:"}}
    if active_low_balance_keys:
        stale_low_balance_query["key"]["$nin"] = list(active_low_balance_keys)
    await db.notifications.delete_many(stale_low_balance_query)

    # Clear stale threshold notifications when balance recovers.
    stale_balance_threshold_query = {
        "user_id": uid,
        "key": {"$regex": r"^balance_threshold:"},
    }
    if active_balance_threshold_keys:
        stale_balance_threshold_query["key"]["$nin"] = list(active_balance_threshold_keys)
    await db.notifications.delete_many(stale_balance_threshold_query)

    # Keep only today's scheduled notifications.
    stale_scheduled_today_query = {
        "user_id": uid,
        "key": {"$regex": r"^scheduled_today:"},
    }
    if active_scheduled_today_keys:
        stale_scheduled_today_query["key"]["$nin"] = list(active_scheduled_today_keys)
    await db.notifications.delete_many(stale_scheduled_today_query)

    cutoff = datetime.now(timezone.utc) - timedelta(days=10)
    notifications = await list_notifications(
        user_id=uid,
        unread_only=False,
        limit=500,
        since=cutoff,
        include_unread_outside_since=True,
    )
    for n in notifications:
        n["id"] = str(n["_id"])
    return notifications


# ======================================================
# RECENT TRANSACTIONS
# ======================================================

async def get_recent_transactions(user_id: str, limit: int = 5):
    uid = ObjectId(user_id)

    account_cursor = db.accounts.find(
        {"user_id": uid, "deleted_at": None},
        {"name": 1},
    )
    account_map = {}
    async for acc in account_cursor:
        account_map[str(acc["_id"])] = acc.get("name")

    cursor = (
        db.transactions
        .find(
            {
                "user_id": uid,
                "deleted_at": None,
                "is_failed": {"$ne": True},
            }
        )
        .sort("created_at", -1)
        .limit(limit * 3)
    )

    raw = [tx async for tx in cursor]
    merged = []
    seen_transfers = set()

    for tx in raw:
        if len(merged) >= limit:
            break

        transfer_id = tx.get("transfer_id")
        if transfer_id:
            key = str(transfer_id)
            if key in seen_transfers:
                continue

            counterpart = await db.transactions.find_one(
                {
                    "user_id": uid,
                    "deleted_at": None,
                    "is_failed": {"$ne": True},
                    "transfer_id": transfer_id,
                    "type": {"$in": ["transfer_in", "transfer_out"]},
                    "_id": {"$ne": tx["_id"]},
                }
            )

            source_tx = tx if tx["type"] == "transfer_out" else counterpart
            target_tx = counterpart if tx["type"] == "transfer_out" else tx

            if source_tx and target_tx:
                merged.append(
                    {
                        "type": "transfer",
                        "amount": tx.get("amount", 0),
                        "description": tx.get("description", "Transfer"),
                        "created_at": tx.get("created_at"),
                        "transfer": {
                            "source": account_map.get(str(source_tx.get("account_id")), "Source"),
                            "target": account_map.get(str(target_tx.get("account_id")), "Target"),
                        },
                    }
                )
                seen_transfers.add(key)
                continue

            account_name = account_map.get(str(tx.get("account_id")), "Account")
            merged.append(
                {
                    "type": "transfer",
                    "amount": tx.get("amount", 0),
                    "description": tx.get("description", "Transfer"),
                    "created_at": tx.get("created_at"),
                    "transfer": {
                        "source": account_name if tx.get("type") == "transfer_out" else "Unknown",
                        "target": account_name if tx.get("type") == "transfer_in" else "Unknown",
                    },
                }
            )
            seen_transfers.add(key)
            continue

        tx["account_name"] = account_map.get(str(tx.get("account_id")))
        merged.append(tx)

    return merged
