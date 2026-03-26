import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.helpers.recurring_schedule import legacy_cron_to_time, parse_clock_time, parse_timezone_name
from app.services.admin_settings import get_admin_settings
from app.services.backups import run_backup

logger = logging.getLogger(__name__)
BACKUP_JOB_ID = "automatic-backups"


async def run_scheduled_backup() -> None:
    try:
        await run_backup(actor={"username": "scheduler", "auth_provider": "system"})
        logger.info("Automatic backup completed")
    except Exception:
        logger.exception("Automatic backup failed")


async def configure_backup_schedule(scheduler: AsyncIOScheduler) -> None:
    cfg = await get_admin_settings()
    backup_cfg = (cfg.get("backup") or {}).copy()
    app_cfg = (cfg.get("application") or {}).copy()
    enabled = bool(backup_cfg.get("enabled"))
    provider = str(backup_cfg.get("provider") or "filesystem").strip().lower()
    schedule_time = str(backup_cfg.get("schedule_time") or legacy_cron_to_time(backup_cfg.get("schedule_cron"))).strip()
    timezone_name = str(app_cfg.get("timezone") or "Asia/Kolkata").strip() or "Asia/Kolkata"

    existing = scheduler.get_job(BACKUP_JOB_ID)
    if existing:
        scheduler.remove_job(BACKUP_JOB_ID)

    if not enabled:
        logger.info("Automatic backups disabled")
        return

    if provider != "filesystem":
        logger.warning("Automatic backup skipped: unsupported provider '%s'", provider)
        return

    if not schedule_time:
        logger.warning("Automatic backup skipped: no schedule time configured")
        return

    try:
        hour, minute = parse_clock_time(schedule_time)
        timezone_obj = parse_timezone_name(timezone_name)
        trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone_obj)
    except ValueError:
        logger.exception("Invalid backup scheduler configuration: %s %s", schedule_time, timezone_name)
        return

    scheduler.add_job(
        run_scheduled_backup,
        trigger=trigger,
        id=BACKUP_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Automatic backup scheduled for %s %s", schedule_time, timezone_name)
