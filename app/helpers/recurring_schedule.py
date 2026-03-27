import re
from datetime import datetime, date, time, timezone
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo, available_timezones

VALID_FREQUENCIES = {
    "daily",
    "weekly",
    "biweekly",
    "monthly",
    "quarterly",
    "halfyearly",
    "yearly",
}

# Default behavior: do not backfill missed schedule instances.
SKIP_MISSED_OCCURRENCES = True

TZ_MAP = {
    "IST": "Asia/Kolkata",
    "UTC": "UTC",
}
DEFAULT_APP_TIMEZONE = "Asia/Kolkata"


def get_timezone_choices() -> list[str]:
    preferred = [
        "Asia/Kolkata",
        "UTC",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "Europe/London",
        "Europe/Berlin",
        "Asia/Dubai",
        "Asia/Singapore",
        "Asia/Tokyo",
        "Australia/Sydney",
    ]
    known = set(preferred)
    remaining = sorted(tz for tz in available_timezones() if tz not in known)
    return preferred + remaining


def parse_timezone_name(value: str | None) -> ZoneInfo:
    raw = str(value or "").strip() or DEFAULT_APP_TIMEZONE
    try:
        return ZoneInfo(raw)
    except Exception as exc:
        raise ValueError(f"Unsupported timezone: {raw}") from exc


def parse_clock_time(value: str) -> tuple[int, int]:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Time is required.")
    match = re.match(r"^(\d{2}):(\d{2})$", raw)
    if not match:
        raise ValueError("Invalid time format. Expected HH:MM.")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour < 0 or hour > 23:
        raise ValueError("Hour must be between 00 and 23.")
    if minute < 0 or minute > 59:
        raise ValueError("Minute must be between 00 and 59.")
    return hour, minute


def legacy_cron_to_time(cron_expr: str | None) -> str:
    raw = str(cron_expr or "").strip()
    match = re.match(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$", raw)
    if not match:
        return ""
    minute = int(match.group(1))
    hour = int(match.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def parse_scheduler_time(time_string: str, timezone_name: str | None = None):
    if timezone_name is not None:
        hour, minute = parse_clock_time(time_string)
        return hour, minute, parse_timezone_name(timezone_name)

    if not time_string:
        raise ValueError("SCHEDULER_RUN_TIME not provided")

    raw = time_string.strip()
    modern_match = re.match(r"^(\d{2}):(\d{2})$", raw)
    if modern_match:
        hour, minute = parse_clock_time(raw)
        return hour, minute, parse_timezone_name(DEFAULT_APP_TIMEZONE)

    pattern = r"^(\d{1,2}):(\d{2})\s(AM|PM)\s([A-Z]+)$"
    match = re.match(pattern, raw)
    if not match:
        raise ValueError("Invalid format. Expected 'HH:MM' or legacy '5:41 AM IST'.")

    hour, minute, am_pm, tz_abbr = match.groups()
    hour = int(hour)
    minute = int(minute)
    if hour < 1 or hour > 12:
        raise ValueError("Hour must be between 1 and 12")
    if minute < 0 or minute > 59:
        raise ValueError("Minute must be between 0 and 59")
    if am_pm == "PM" and hour != 12:
        hour += 12
    elif am_pm == "AM" and hour == 12:
        hour = 0
    if tz_abbr not in TZ_MAP:
        raise ValueError(f"Unsupported timezone: {tz_abbr}")
    return hour, minute, ZoneInfo(TZ_MAP[tz_abbr])


def _frequency_delta(frequency: str) -> relativedelta:
    if frequency == "daily":
        return relativedelta(days=1)
    if frequency == "weekly":
        return relativedelta(weeks=1)
    if frequency == "biweekly":
        return relativedelta(weeks=2)
    if frequency == "monthly":
        return relativedelta(months=1)
    if frequency == "quarterly":
        return relativedelta(months=3)
    if frequency == "halfyearly":
        return relativedelta(months=6)
    if frequency == "yearly":
        return relativedelta(years=1)
    raise ValueError(f"Unsupported frequency: {frequency}")


def calculate_next_run(
    last_run: date | None,
    start_date: date,
    frequency: str,
) -> datetime:
    if frequency not in VALID_FREQUENCIES:
        raise ValueError(f"Unsupported frequency: {frequency}")

    base_date = last_run or start_date
    return datetime.combine(base_date, datetime.min.time()) + _frequency_delta(frequency)


def calculate_next_occurrence(
    *,
    start_date: date,
    frequency: str,
    today: date | None = None,
    include_today: bool = False,
    skip_missed: bool = SKIP_MISSED_OCCURRENCES,
) -> datetime:
    if not start_date:
        raise ValueError("start_date is required")
    if frequency not in VALID_FREQUENCIES:
        raise ValueError(f"Unsupported frequency: {frequency}")

    today_date = today or datetime.now(timezone.utc).date()
    candidate = datetime.combine(start_date, time.min, tzinfo=timezone.utc)

    if not skip_missed:
        return candidate

    if include_today:
        if candidate.date() >= today_date:
            return candidate
    else:
        if candidate.date() > today_date:
            return candidate

    guard = 0
    while guard < 1000:
        candidate = calculate_next_run(
            last_run=candidate.date(),
            start_date=start_date,
            frequency=frequency,
        )
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=timezone.utc)
        if include_today and candidate.date() >= today_date:
            return candidate
        if not include_today and candidate.date() > today_date:
            return candidate
        guard += 1

    raise RuntimeError("Unable to calculate next recurring occurrence")
