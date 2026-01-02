from datetime import datetime, timedelta, timezone

EDIT_WINDOW_DAYS = 2  # today + yesterday
RESTORE_WINDOW_HOURS = 24

now = datetime.now(timezone.utc)

def is_within_edit_window(dt):
    if not dt:
        return False

    # ✅ Normalize to UTC-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    cutoff = datetime.now(timezone.utc) - timedelta(days=EDIT_WINDOW_DAYS)
    return dt >= cutoff


def is_month_closed(dt_utc, closed_months):
    return any(
        m["year"] == dt_utc.year and m["month"] == dt_utc.month
        for m in closed_months
    )

def can_restore_today(deleted_at_utc):
    if deleted_at_utc is None:
        return False

    now = datetime.now(timezone.utc)
    return deleted_at_utc.date() == now.date()

