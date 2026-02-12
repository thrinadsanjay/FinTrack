import logging
from datetime import datetime, timezone
from app.core.logging import setup_logging
from app.db.mongo import db
from app.services.recurring_deposit import calculate_next_run
from app.services.notifications import upsert_notification

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
        scheduled_for = r.get("next_run")
        if scheduled_for and scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

        if not scheduled_for:
            continue

        # -----------------------------
        # Idempotency guard
        # -----------------------------
        existing = await db[TRANSACTIONS].find_one({
            "recurring_id": r["_id"],
            "scheduled_for": scheduled_for,
            "deleted_at": None,
        })

        if existing:
            continue  # already posted for this run

        account = await db[ACCOUNTS].find_one(
            {"_id": r["account_id"]},
            {"balance": 1, "name": 1},
        )
        account_balance = account.get("balance", 0) if account else 0

        if r["type"] == "debit" and account_balance < r["amount"]:
            failed_tx_doc = {
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
                "scheduled_for": scheduled_for,
                "is_failed": True,
                "failure_reason": "insufficient_funds",
                "retry_status": "pending",
            }
            await db[TRANSACTIONS].insert_one(failed_tx_doc)
            logger.warning("Recurring transaction failed (insufficient funds): %s", failed_tx_doc)

            schedule_key = scheduled_for.strftime("%Y%m%d%H%M")
            await upsert_notification(
                user_id=r["user_id"],
                key=f"recurring_failed:{str(r['_id'])}:{schedule_key}",
                notif_type="warning",
                title="Recurring transaction failed",
                message=(
                    f"{account.get('name', 'Account') if account else 'Account'} has ₹ {account_balance}, "
                    f"but ₹ {r['amount']} is required for {r.get('description', 'a recurring transaction')}."
                ),
            )
            continue

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
            "scheduled_for": scheduled_for,
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
            last_run=scheduled_for.date(),
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
                    "last_run": scheduled_for,
                    "next_run": next_run,
                }
            }
        )
