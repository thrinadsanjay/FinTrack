from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from app.db.mongo import db

TRANSACTIONS = "transactions"
RECURRING_TRANSACTIONS = "recurring_transactions"

def calculate_next_run(r):
    if r["frequency"] == "daily":
        return r["next_run"] + timedelta(days=r["interval"])
    if r["frequency"] == "weekly":
        return r["next_run"] + timedelta(weeks=r["interval"])
    if r["frequency"] == "monthly":
        return r["next_run"] + relativedelta(months=r["interval"])
    if r["frequency"] == "yearly":
        return r["next_run"] + relativedelta(years=r["interval"])

def run_recurring_transactions():
    today = date.today()

    recurrences = db[RECURRING_TRANSACTIONS].find({
        "is_active": True,
        "next_run": {"$lte": today}
    })

    for r in recurrences:
        if r.get("auto_post", True):
            db[TRANSACTIONS].insert_one({
                "user_id": r["user_id"],
                "name": r["name"],
                "amount": r["amount"],
                "category_id": r["category_id"],
                "transaction_type": r["transaction_type"],
                "date": r["next_run"],
                "source": "recurring"
            })

        db[RECURRING_TRANSACTIONS].update_one(
            {"_id": r["_id"]},
            {
                "$set": {
                    "last_run": today,
                    "next_run": calculate_next_run(r)
                }
            }
        )
