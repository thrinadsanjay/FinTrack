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

from datetime import datetime, timezone
from bson import ObjectId
from app.db.mongo import db


# ======================================================
# TIME HELPERS (UTC)
# ======================================================

def start_of_today_utc():
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def start_of_month_utc():
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


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

    return {
        "balance": balance,
        "today_credit": today_credit,
        "today_debit": today_debit,
        "month_net": month_credit - month_debit,
    }


# ======================================================
# RECENT TRANSACTIONS
# ======================================================

async def get_recent_transactions(user_id: str, limit: int = 5):
    uid = ObjectId(user_id)

    cursor = (
        db.transactions
        .find(
            {
                "user_id": uid,
                "deleted_at": None,
            }
        )
        .sort("created_at", -1)
        .limit(limit)
    )

    return [tx async for tx in cursor]
