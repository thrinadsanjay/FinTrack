from datetime import datetime, timezone, timedelta
from bson import ObjectId

from app.db.mongo import db
from app.helpers.dashboard_time import APP_TIMEZONE, APP_ZONE


async def fetch_total_balance(uid: ObjectId) -> float:
    balance_cursor = db.accounts.aggregate(
        [
            {"$match": {"user_id": uid, "deleted_at": None}},
            {"$group": {"_id": None, "total": {"$sum": "$balance"}}},
        ]
    )
    total = 0.0
    async for row in balance_cursor:
        total = row.get("total", 0) or 0
    return total


async def fetch_credit_debit_totals_since(uid: ObjectId, since: datetime) -> tuple[float, float]:
    cursor = db.transactions.aggregate(
        [
            {
                "$match": {
                    "user_id": uid,
                    "deleted_at": None,
                    "is_failed": {"$ne": True},
                    "created_at": {"$gte": since},
                }
            },
            {"$group": {"_id": "$type", "total": {"$sum": "$amount"}}},
        ]
    )
    credit = debit = 0.0
    async for row in cursor:
        if row["_id"] == "credit":
            credit = row.get("total", 0) or 0
        elif row["_id"] == "debit":
            debit = row.get("total", 0) or 0
    return credit, debit


async def fetch_account_balances_and_map(uid: ObjectId) -> tuple[list[dict], dict[str, dict]]:
    accounts_cursor = (
        db.accounts
        .find(
            {"user_id": uid, "deleted_at": None},
            {"name": 1, "bank_name": 1, "balance": 1, "type": 1, "credit_limit": 1},
        )
        .sort("balance", -1)
    )

    balances: list[dict] = []
    account_map: dict[str, dict] = {}
    async for acc in accounts_cursor:
        acc_id = str(acc["_id"])
        row = {
            "id": acc_id,
            "name": acc.get("name"),
            "bank_name": acc.get("bank_name"),
            "balance": acc.get("balance", 0),
            "type": acc.get("type"),
            "credit_limit": acc.get("credit_limit"),
        }
        balances.append(row)
        account_map[acc_id] = {
            "name": row["name"],
            "bank_name": row["bank_name"],
            "balance": row["balance"],
            "type": row["type"],
            "credit_limit": row["credit_limit"],
        }
    return balances, account_map


async def fetch_top_spending_categories(uid: ObjectId, month_start: datetime, month_debit: float) -> list[dict]:
    if month_debit <= 0:
        return []
    categories_cursor = db.transactions.aggregate(
        [
            {
                "$match": {
                    "user_id": uid,
                    "deleted_at": None,
                    "is_failed": {"$ne": True},
                    "created_at": {"$gte": month_start},
                    "type": "debit",
                }
            },
            {"$group": {"_id": {"$ifNull": ["$category.name", "Uncategorized"]}, "total": {"$sum": "$amount"}}},
            {"$sort": {"total": -1}},
            {"$limit": 5},
        ]
    )
    items: list[dict] = []
    async for row in categories_cursor:
        total = row.get("total", 0) or 0
        items.append(
            {
                "name": row.get("_id") or "Uncategorized",
                "total": total,
                "percent": round((total / month_debit) * 100, 1) if month_debit else 0,
            }
        )
    return items


async def fetch_largest_transactions(uid: ObjectId, month_start: datetime, account_map: dict[str, dict]) -> list[dict]:
    cursor = (
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
    rows: list[dict] = []
    async for tx in cursor:
        rows.append(
            {
                "description": tx.get("description", "Transaction"),
                "amount": tx.get("amount", 0),
                "created_at": tx.get("created_at"),
                "account_name": account_map.get(str(tx.get("account_id")), {}).get("name", "Account"),
            }
        )
    return rows


async def fetch_daily_trend(uid: ObjectId, trend_start: datetime, trend_end: datetime) -> list[dict]:
    trend_cursor = db.transactions.aggregate(
        [
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
                                "timezone": APP_TIMEZONE,
                            }
                        },
                        "type": "$type",
                    },
                    "total": {"$sum": "$amount"},
                }
            },
        ]
    )

    daily_map: dict[str, dict[str, float]] = {}
    async for row in trend_cursor:
        day = row["_id"]["day"]
        tx_type = row["_id"]["type"]
        daily_map.setdefault(day, {"credit": 0, "debit": 0})
        daily_map[day][tx_type] = row.get("total", 0) or 0

    start_local_date = trend_start.astimezone(APP_ZONE).date()
    end_local_date = trend_end.astimezone(APP_ZONE).date()
    day_count = max((end_local_date - start_local_date).days, 0)
    out: list[dict] = []
    for i in range(day_count):
        day_local_date = start_local_date + timedelta(days=i)
        day_key = day_local_date.strftime("%Y-%m-%d")
        out.append(
            {
                "date": day_key,
                "day": day_local_date.day,
                "income": daily_map.get(day_key, {}).get("credit", 0),
                "expense": daily_map.get(day_key, {}).get("debit", 0),
            }
        )
    return out


async def fetch_monthly_trend_12m(uid: ObjectId, month_anchor: datetime) -> tuple[list[dict], dict[str, dict], str, str]:
    anchor_local = month_anchor.astimezone(APP_ZONE)
    start_year = anchor_local.year
    start_month = anchor_local.month
    for _ in range(11):
        if start_month == 1:
            start_month = 12
            start_year -= 1
        else:
            start_month -= 1
    month_start_local = datetime(start_year, start_month, 1, tzinfo=APP_ZONE)
    month_start = month_start_local.astimezone(timezone.utc)

    monthly_cursor = db.transactions.aggregate(
        [
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
                                "timezone": APP_TIMEZONE,
                            }
                        },
                        "type": "$type",
                    },
                    "total": {"$sum": "$amount"},
                }
            },
        ]
    )

    monthly_map: dict[str, dict[str, float]] = {}
    async for row in monthly_cursor:
        month_key = row["_id"]["month"]
        tx_type = row["_id"]["type"]
        monthly_map.setdefault(month_key, {"credit": 0, "debit": 0})
        monthly_map[month_key][tx_type] = row.get("total", 0) or 0

    trend_monthly: list[dict] = []
    current_local = month_start_local
    for _ in range(12):
        month_key = current_local.strftime("%Y-%m")
        credit = monthly_map.get(month_key, {}).get("credit", 0)
        debit = monthly_map.get(month_key, {}).get("debit", 0)
        trend_monthly.append(
            {
                "month": month_key,
                "month_short": current_local.strftime("%b"),
                "month_label": current_local.strftime("%b %Y"),
                "income": credit,
                "expense": debit,
                "net": credit - debit,
            }
        )
        next_month = (current_local.month % 12) + 1
        next_year = current_local.year + (1 if current_local.month == 12 else 0)
        current_local = datetime(next_year, next_month, 1, tzinfo=APP_ZONE)

    range_label = ""
    if trend_monthly:
        range_label = f"{trend_monthly[0]['month_label']} - {trend_monthly[-1]['month_label']}"
    till_label = anchor_local.strftime("%b %Y")
    return trend_monthly, monthly_map, range_label, till_label


def build_credit_card_alerts(account_balances: list[dict], notifications: list[dict]) -> list[dict]:
    alerts = [
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
        if not credit_limit or credit_limit <= 0:
            continue
        balance_value = abs(account.get("balance", 0))
        usage_ratio = balance_value / credit_limit
        if usage_ratio >= 0.8:
            usage_percent = round(usage_ratio * 100)
            alerts.append(
                {
                    "level": "warning",
                    "title": "Credit card nearing limit",
                    "message": (
                        f"{account.get('name', 'Credit card')} is at "
                        f"{usage_percent}% of its ₹ {credit_limit} limit."
                    ),
                }
            )
    return alerts
