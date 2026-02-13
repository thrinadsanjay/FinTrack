from datetime import datetime, timezone


def start_of_today_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


def start_of_month_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def start_of_day_utc(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def next_month_start(dt: datetime) -> datetime:
    return datetime(
        dt.year + (1 if dt.month == 12 else 0),
        1 if dt.month == 12 else dt.month + 1,
        1,
        tzinfo=timezone.utc,
    )
