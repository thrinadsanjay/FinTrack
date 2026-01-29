"""
Time-based guard utilities.

Responsibilities:
- Enforce edit window rules
- Enforce restore window rules
- Support month-close logic

Must remain:
- Pure
- Stateless
- Side-effect free
"""

from datetime import datetime, timedelta, timezone
from fastapi.responses import RedirectResponse
from functools import wraps

# ======================================================
# CONFIGURABLE WINDOWS
# ======================================================

EDIT_WINDOW_DAYS = 2        # today + yesterday
RESTORE_WINDOW_HOURS = 24  # rolling window

# ======================================================
# LOGIN REQUIRED DECORATOR
# ======================================================

def login_required(f):
    @wraps(f)
    async def decorated_function(request, *args, **kwargs):
        user = request.session.get("user")
        if not user:
            return RedirectResponse("/login", status_code=303)
        return await f(request, *args, **kwargs)
    return decorated_function

# ======================================================
# EDIT WINDOW
# ======================================================

def is_within_edit_window(dt) -> bool:
    """
    Returns True if datetime is within editable window.
    """
    if not dt:
        return False

    # Normalize to UTC-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    cutoff = datetime.now(timezone.utc) - timedelta(days=EDIT_WINDOW_DAYS)
    return dt >= cutoff


# ======================================================
# MONTH CLOSE
# ======================================================

def is_month_closed(dt_utc, closed_months: list[dict]) -> bool:
    """
    Checks whether the given datetime falls in a closed month.
    """
    return any(
        m["year"] == dt_utc.year and m["month"] == dt_utc.month
        for m in closed_months
    )


# ======================================================
# RESTORE WINDOW
# ======================================================

def can_restore_today(deleted_at_utc) -> bool:
    """
    Returns True if a transaction can be restored
    within the rolling restore window.
    """
    if not deleted_at_utc:
        return False

    if deleted_at_utc.tzinfo is None:
        deleted_at_utc = deleted_at_utc.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    return now - deleted_at_utc <= timedelta(hours=RESTORE_WINDOW_HOURS)
