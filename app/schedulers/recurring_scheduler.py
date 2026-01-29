import logging
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from app.core.logging import setup_logging
from app.db.mongo import db
from app.services.recurring_deposit import calculate_next_run

setup_logging()
logger = logging.getLogger(__name__)

# ======================================================
# COLLECTION NAMES
# ======================================================

TRANSACTIONS = "transactions"
RECURRING = "recurring_deposits"
ACCOUNTS = "accounts"


# ======================================================
# ASYNC SCHEDULER JOB
# ======================================================

async def run_recurring_transactions():
    """
    Materializes recurring transactions whose next_run is due.

    SAFE PROPERTIES:
    - Async (Motor-compatible)
    - Idempotent (won't double-post)
    - UTC-based
    """

    now = datetime.now(timezone.utc)

    recurrences = db[RECURRING].find({
        "is_active": True,
        "next_run": {"$lte": now},
    })

    async for r in recurrences:
        # -----------------------------
        # Idempotency guard
        # -----------------------------
        existing = await db[TRANSACTIONS].find_one({
            "recurring_id": r["_id"],
            "created_at": {
                "$gte": r["next_run"],
                "$lt": r["next_run"] + timedelta(minutes=1),
            }
        })

        if existing:
            continue  # already posted for this run

        # -----------------------------
        # Create transaction
        # -----------------------------
        tx_doc = {
            "user_id": r["user_id"],
            "account_id": r["account_id"],
            "type": r["type"],
            "mode": r["mode"],
            "amount": r["amount"],
            "description": r.get("description", ""),
            "category": r["category"],
            "subcategory": r["subcategory"],
            "created_at": now,
            "deleted_at": None,
            "source": "recurring",
            "recurring_id": r["_id"],
        }

        await db[TRANSACTIONS].insert_one(tx_doc)
        logger.info("⏱ Recurring transaction inserted: %s", tx_doc)

        # -----------------------------
        # Update account balance
        # -----------------------------
        delta = r["amount"] if r["type"] == "credit" else -r["amount"]

        await db[ACCOUNTS].update_one(
            {"_id": r["account_id"]},
            {"$inc": {"balance": delta}},
        )

        # -----------------------------
        # Calculate next run
        # -----------------------------
        next_run = calculate_next_run(
            last_run=r["next_run"].date(),
            start_date=r["start_date"].date(),
            frequency=r["frequency"],
        )

        # -----------------------------
        # Update recurring rule
        # -----------------------------
        await db[RECURRING].update_one(
            {"_id": r["_id"]},
            {
                "$set": {
                    "last_run": r["next_run"],
                    "next_run": next_run,
                }
            }
        )
