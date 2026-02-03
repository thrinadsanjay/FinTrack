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

async def _fetch_upcoming_bills(uid: ObjectId, account_map: dict):
    now = datetime.now(timezone.utc)
    upcoming_end = now + timedelta(days=30)
    upcoming_7_end = now + timedelta(days=7)

    recurring_cursor = db.recurring_deposits.find(
        {
            "user_id": uid,
            "is_active": True,
            "next_run": {"$gte": now, "$lte": upcoming_end},
        }
    ).sort("next_run", 1)

    upcoming_bills_7 = []
    upcoming_bills_30 = []
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

        upcoming_bills_30.append(item)
        if item["due_at"] and item["due_at"] <= upcoming_7_end:
            upcoming_bills_7.append(item)

        if item["type"] == "debit":
            required_by_account[account_id] = (
                required_by_account.get(account_id, 0) + item["amount"]
            )

    return upcoming_bills_7, upcoming_bills_30, required_by_account


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
            {"name": 1, "bank_name": 1, "balance": 1},
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
            }
        )
        account_map[acc_id] = {
            "name": acc.get("name"),
            "bank_name": acc.get("bank_name"),
            "balance": acc.get("balance", 0),
        }

    # -----------------------------
    # DAILY TREND (LAST 14 DAYS)
    # -----------------------------
    today = datetime.now(timezone.utc)
    trend_start = start_of_day_utc(today - timedelta(days=13))

    trend_cursor = db.transactions.aggregate([
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
                "created_at": {"$gte": trend_start},
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
    for i in range(14):
        day_dt = trend_start + timedelta(days=i)
        day_key = day_dt.strftime("%Y-%m-%d")
        credit = daily_map.get(day_key, {}).get("credit", 0)
        debit = daily_map.get(day_key, {}).get("debit", 0)
        trend_daily.append(
            {
                "date": day_key,
                "income": credit,
                "expense": debit,
                "net": credit - debit,
            }
        )

    # -----------------------------
    # MONTHLY TREND (LAST 6 MONTHS)
    # -----------------------------
    month_anchor = start_of_month_utc()
    month_start = datetime(
        month_anchor.year,
        month_anchor.month,
        1,
        tzinfo=timezone.utc,
    ) - timedelta(days=31 * 5)
    month_start = datetime(month_start.year, month_start.month, 1, tzinfo=timezone.utc)

    monthly_cursor = db.transactions.aggregate([
        {
            "$match": {
                "user_id": uid,
                "deleted_at": None,
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
    for _ in range(6):
        month_key = current.strftime("%Y-%m")
        credit = monthly_map.get(month_key, {}).get("credit", 0)
        debit = monthly_map.get(month_key, {}).get("debit", 0)
        trend_monthly.append(
            {
                "month": month_key,
                "income": credit,
                "expense": debit,
                "net": credit - debit,
            }
        )
        next_month = (current.month % 12) + 1
        next_year = current.year + (1 if current.month == 12 else 0)
        current = datetime(next_year, next_month, 1, tzinfo=timezone.utc)

    # -----------------------------
    # UPCOMING BILLS (NEXT 7 / 30 DAYS)
    # -----------------------------
    upcoming_bills_7, upcoming_bills_30, required_by_account = (
        await _fetch_upcoming_bills(uid, account_map)
    )

    notifications = await _persist_notifications(
        uid=uid,
        required_by_account=required_by_account,
        account_map=account_map,
    )

    return {
        "balance": balance,
        "today_credit": today_credit,
        "today_debit": today_debit,
        "today_income": today_credit,
        "today_expense": today_debit,
        "month_net": month_credit - month_debit,
        "account_balances": account_balances,
        "trend_daily": trend_daily,
        "trend_monthly": trend_monthly,
        "upcoming_bills_7": upcoming_bills_7,
        "upcoming_bills_30": upcoming_bills_30,
        "notifications": notifications,
    }


async def get_user_notifications(user_id: str):
    uid = ObjectId(user_id)
    accounts_cursor = (
        db.accounts
        .find(
            {"user_id": uid, "deleted_at": None},
            {"name": 1, "bank_name": 1, "balance": 1},
        )
    )
    account_map = {}
    async for acc in accounts_cursor:
        account_map[str(acc["_id"])] = {
            "name": acc.get("name"),
            "bank_name": acc.get("bank_name"),
            "balance": acc.get("balance", 0),
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
    active_keys = []
    for account_id, required in required_by_account.items():
        account_info = account_map.get(account_id, {})
        balance_value = account_info.get("balance", 0)
        if balance_value < required:
            key = f"low_balance:{account_id}"
            active_keys.append(key)
            await upsert_notification(
                user_id=uid,
                key=key,
                notif_type="warning",
                title="Low balance for upcoming bills",
                message=(
                    f"{account_info.get('name', 'Account')} needs ₹ {required} "
                    f"but has ₹ {balance_value}."
                ),
            )

    if active_keys:
        await db.notifications.update_many(
            {
                "user_id": uid,
                "key": {"$regex": "^low_balance:"},
                "key": {"$nin": active_keys},
            },
            {"$set": {"is_read": True, "updated_at": datetime.now(timezone.utc)}},
        )

    notifications = await list_notifications(user_id=uid, unread_only=True, limit=20)
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
