"""
Time & timezone utilities.

Used by:
- Web layer (templates, UI)
- Services (date range conversion)
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Kolkata"


def get_user_timezone(request) -> ZoneInfo:
    """
    Returns user's timezone from session or default.
    """
    tz_name = request.session.get("timezone", DEFAULT_TZ)
    return ZoneInfo(tz_name)


def utc_to_local(dt, user_tz: ZoneInfo):
    """
    Convert UTC datetime → user timezone.
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(user_tz)


def local_date_range_to_utc(date_from: str, date_to: str, user_tz: ZoneInfo):
    """
    Convert local date range → UTC datetime range.
    """
    start = datetime.fromisoformat(date_from).replace(tzinfo=user_tz)
    end = datetime.fromisoformat(date_to).replace(tzinfo=user_tz)

    return (
        start.astimezone(timezone.utc),
        end.astimezone(timezone.utc),
    )


# ------------------------------------------------------
# TEMPLATE HELPERS
# ------------------------------------------------------

def localtime(dt, request):
    return utc_to_local(dt, get_user_timezone(request))


def datetimeformat(value, fmt="%d-%m-%Y %I:%M %p"):
    return value.strftime(fmt) if value else ""


def dateformat(value, fmt="%d-%m-%Y"):
    return value.strftime(fmt) if value else ""
