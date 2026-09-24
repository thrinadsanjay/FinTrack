import logging

from app.schedulers.job_lock import singleton_job
from app.db.mongo import db
from app.services.dashboard import get_user_notifications

logger = logging.getLogger(__name__)


@singleton_job("notification-alert-sweep", lease_seconds=15 * 60)
async def run_notification_alert_sweep() -> None:
    """
    Recompute user dashboard notifications in background.
    This triggers Telegram mirroring for eligible new/updated alerts.
    """
    cursor = db.users.find(
        {
            "deleted_at": None,
            "is_active": True,
        },
        {"_id": 1},
    )

    processed = 0
    async for user in cursor:
        try:
            await get_user_notifications(str(user["_id"]))
            from app.services.rules import evaluate_snapshot_rules

            await evaluate_snapshot_rules(str(user["_id"]))
            processed += 1
        except Exception:
            logger.exception("Notification sweep failed for user_id=%s", str(user.get("_id")))

    logger.info("Notification alert sweep completed for %s active users", processed)
