from datetime import datetime, date, time, timezone
from dateutil.relativedelta import relativedelta

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
