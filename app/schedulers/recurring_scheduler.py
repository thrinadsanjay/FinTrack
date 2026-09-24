import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import setup_logging
from app.db.mongo import db, run_atomic
from app.schedulers.job_lock import singleton_job
from app.helpers.account_balances import apply_account_delta, delta_for_tx
from app.helpers.notification_payloads import recurring_failed_scheduler_payload
from app.helpers.recurring_schedule import (
    calculate_next_run,
    calculate_next_occurrence,
    parse_clock_time,
    parse_timezone_name,
    SKIP_MISSED_OCCURRENCES,
)
from app.services.admin_settings import get_admin_settings
from app.services.notifications import upsert_notification
from app.helpers.money import round_money

setup_logging()
logger = logging.getLogger(__name__)

# ======================================================
# COLLECTION NAMES
# ======================================================

TRANSACTIONS = "transactions"
RECURRING = "recurring_deposits"
ACCOUNTS = "accounts"
RECURRING_JOB_ID = "recurring-transactions"


async def configure_recurring_schedule(scheduler: AsyncIOScheduler) -> None:
    cfg = await get_admin_settings()
    app_cfg = (cfg.get("application") or {}).copy()
    timezone_name = str(app_cfg.get("timezone") or os.getenv("FT_APP_TIMEZONE", "Asia/Kolkata")).strip() or "Asia/Kolkata"
    run_time = str(app_cfg.get("scheduler_run_time") or os.getenv("SCHEDULER_RUN_TIME", "05:41")).strip() or "05:41"

    existing = scheduler.get_job(RECURRING_JOB_ID)
    if existing:
        scheduler.remove_job(RECURRING_JOB_ID)

    try:
        hour, minute = parse_clock_time(run_time)
        timezone_obj = parse_timezone_name(timezone_name)
    except ValueError:
        logger.exception("Invalid recurring scheduler configuration: %s %s", run_time, timezone_name)
        return

    scheduler.add_job(
        run_recurring_transactions,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=timezone_obj,
        id=RECURRING_JOB_ID,
        replace_existing=True,
    )
    logger.info("Recurring scheduler configured for %s", run_time)


# ======================================================
# ASYNC SCHEDULER JOB
# ======================================================

@singleton_job("recurring-transactions", lease_seconds=30 * 60)
async def run_recurring_transactions():
    """
    Materializes recurring transactions whose next_run is due.

    SAFE PROPERTIES:
    - Async (Motor-compatible)
    - Idempotent (won't double-post)
    - UTC-based
    """

    now = datetime.now(timezone.utc)
    today_date = now.date()

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

        # Skip stale past runs by default (no automatic backfill).
        if SKIP_MISSED_OCCURRENCES and scheduled_for.date() < today_date:
            next_run = calculate_next_occurrence(
                start_date=r["start_date"].date(),
                frequency=r["frequency"],
                today=today_date,
                include_today=False,
                skip_missed=True,
            )
            if next_run <= scheduled_for:
                next_run = calculate_next_run(
                    last_run=scheduled_for.date(),
                    start_date=r["start_date"].date(),
                    frequency=r["frequency"],
                )
                if next_run.tzinfo is None:
                    next_run = next_run.replace(tzinfo=timezone.utc)
            await db[RECURRING].update_one(
                {"_id": r["_id"]},
                {
                    "$set": {
                        "next_run": next_run,
                        "updated_at": now,
                    }
                },
            )
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

        amount = round_money(r.get("amount", 0))

        # -----------------------------
        # Create transaction + update balance (atomic; debit is funds-guarded)
        # -----------------------------
        tx_doc = {
            "user_id": r["user_id"],
            "account_id": r["account_id"],
            "type": r["type"],
            "mode": r["mode"],
            "amount": amount,
            "description": r.get("description", ""),
            "category": r["category"],
            "subcategory": r["subcategory"],
            "created_at": now,
            "deleted_at": None,
            "source": "recurring",
            "recurring_id": r["_id"],
            "scheduled_for": scheduled_for,
        }
        delta = delta_for_tx(r["type"], amount)

        async def _post(session, tx_doc=tx_doc, delta=delta, account_id=r["account_id"]):
            if not await apply_account_delta(
                db=db,
                account_id=account_id,
                delta=delta,
                session=session,
                require_funds=True,
            ):
                return False
            try:
                await db[TRANSACTIONS].insert_one(dict(tx_doc), session=session)
            except Exception:
                if session is None:
                    await apply_account_delta(db=db, account_id=account_id, delta=-delta)
                raise
            return True

        if not await run_atomic(_post):
            account = await db[ACCOUNTS].find_one(
                {"_id": r["account_id"]},
                {"balance": 1, "name": 1},
            )
            account_balance = account.get("balance", 0) if account else 0
            failed_tx_doc = {
                **tx_doc,
                "is_failed": True,
                "failure_reason": "insufficient_funds",
                "retry_status": "pending",
            }
            await db[TRANSACTIONS].insert_one(failed_tx_doc)
            logger.warning("Recurring transaction failed (insufficient funds): %s", failed_tx_doc)

            schedule_key = scheduled_for.strftime("%Y%m%d%H%M")
            await upsert_notification(
                user_id=r["user_id"],
                **recurring_failed_scheduler_payload(
                    recurring_id=str(r["_id"]),
                    schedule_key=schedule_key,
                    account_name=account.get("name", "Account") if account else "Account",
                    balance=account_balance,
                    amount=amount,
                    description=r.get("description", "a recurring transaction"),
                ),
            )
            continue

        logger.info("⏱ Recurring transaction inserted: %s", tx_doc)

        # -----------------------------
        # Calculate next run
        # -----------------------------
        next_run = calculate_next_run(
            last_run=scheduled_for.date(),
            start_date=r["start_date"].date(),
            frequency=r["frequency"],
        )
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)

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
