import logging

from app.schedulers.job_lock import singleton_job
from app.services.credit_cards import (
    run_bill_generation_job,
    run_due_alert_job,
    run_emi_schedule_job,
    run_interest_and_late_fee_job,
)

logger = logging.getLogger(__name__)


@singleton_job("credit-card-bill-generation", lease_seconds=30 * 60)
async def run_credit_card_bill_generation() -> None:
    generated = await run_bill_generation_job()
    logger.info("Credit card bill generation completed: %s bills generated", generated)


@singleton_job("credit-card-due-alerts", lease_seconds=30 * 60)
async def run_credit_card_due_alerts() -> None:
    sent = await run_due_alert_job()
    logger.info("Credit card due alerts processed: %s alerts sent", sent)


@singleton_job("credit-card-interest-fees", lease_seconds=30 * 60)
async def run_credit_card_interest_and_fees() -> None:
    processed = await run_interest_and_late_fee_job()
    logger.info("Credit card interest/late fee sweep completed: %s overdue bills processed", processed)


@singleton_job("credit-card-emi-refresh", lease_seconds=30 * 60)
async def run_credit_card_emi_schedule_refresh() -> None:
    created = await run_emi_schedule_job()
    logger.info("Credit card EMI schedule refresh completed: %s schedule rows created", created)
