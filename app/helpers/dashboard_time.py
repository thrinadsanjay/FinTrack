from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.time import DEFAULT_TZ

APP_TIMEZONE = DEFAULT_TZ
APP_ZONE = ZoneInfo(APP_TIMEZONE)


def app_now() -> datetime:
    return datetime.now(APP_ZONE)


def start_of_today_utc() -> datetime:
    now_local = app_now()
    local_start = datetime(now_local.year, now_local.month, now_local.day, tzinfo=APP_ZONE)
    return local_start.astimezone(timezone.utc)


def start_of_month_utc() -> datetime:
    now_local = app_now()
    local_start = datetime(now_local.year, now_local.month, 1, tzinfo=APP_ZONE)
    return local_start.astimezone(timezone.utc)


def start_of_day_utc(dt: datetime) -> datetime:
    source = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    local_dt = source.astimezone(APP_ZONE)
    local_start = datetime(local_dt.year, local_dt.month, local_dt.day, tzinfo=APP_ZONE)
    return local_start.astimezone(timezone.utc)


def next_month_start(dt: datetime) -> datetime:
    source = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    local_dt = source.astimezone(APP_ZONE)
    local_next = datetime(
        local_dt.year + (1 if local_dt.month == 12 else 0),
        1 if local_dt.month == 12 else local_dt.month + 1,
        1,
        tzinfo=APP_ZONE,
    )
    return local_next.astimezone(timezone.utc)
