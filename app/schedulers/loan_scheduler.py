"""Daily catch-up for reducing-balance loan EMI cycles."""

from __future__ import annotations

import logging

from app.schedulers.job_lock import singleton_job
from app.services.loans import apply_all_due_loans

logger = logging.getLogger(__name__)


@singleton_job("loan-emi-cycles", lease_seconds=30 * 60)
async def run_loan_emi_cycles() -> None:
    try:
        applied = await apply_all_due_loans()
        if applied:
            logger.info("Applied %s loan EMI cycle(s)", applied)
    except Exception:
        logger.exception("Loan EMI scheduler failed")
