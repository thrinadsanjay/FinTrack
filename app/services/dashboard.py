from datetime import datetime, timedelta
from bson import ObjectId
from app.db.mongo import db

def start_of_today():
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)

def start_of_month():
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)

async def get_dashboard_summary(user_id: str):
    uid = ObjectId(user_id)

    # Total balance
    balance_cursor = db.accounts.aggregate([
        {"$match": {"user_id": uid}},
        {"$group": {"_id": None, "total": {"$sum": "$balance"}}},
    ])
    balance = 0
    async for row in balance_cursor:
        balance = row["total"]

    # Today income / expense
    today = start_of_today()

    tx_cursor = db.transactions.aggregate([
        {
            "$match": {
                "user_id": uid,
                "created_at": {"$gte": today},
            }
        },
        {
            "$group": {
                "_id": "$type",  # income / expense
                "total": {"$sum": "$amount"},
            }
        },
    ])

    today_income = today_expense = 0
    async for row in tx_cursor:
        if row["_id"] == "income":
            today_income = row["total"]
        elif row["_id"] == "expense":
            today_expense = row["total"]

    # This month net
    month_start = start_of_month()
    month_cursor = db.transactions.aggregate([
        {
            "$match": {
                "user_id": uid,
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

    month_income = month_expense = 0
    async for row in month_cursor:
        if row["_id"] == "income":
            month_income = row["total"]
        elif row["_id"] == "expense":
            month_expense = row["total"]

    return {
        "balance": balance,
        "today_income": today_income,
        "today_expense": today_expense,
        "month_net": month_income - month_expense,
    }

async def get_recent_transactions(user_id: str, limit: int = 5):
    uid = ObjectId(user_id)

    cursor = (
        db.transactions
        .find({"user_id": uid, "deleted_at": None })
        .sort("created_at", -1)
        .limit(limit)
    )

    txs = []
    async for tx in cursor:
        txs.append(tx)

    return txs
