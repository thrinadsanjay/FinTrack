"""
Time & timezone utilities.

Used by:
- Web layer (templates, UI)
- Services (date range conversion)
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Kolkata"


def get_user_timezone(request) -> ZoneInfo:
    """
    Returns user's timezone from session/cookie or default.
    """
    tz_name = DEFAULT_TZ
    try:
        session_tz = str((request.session or {}).get("timezone") or "").strip()
        if session_tz:
            tz_name = session_tz
        cookie_tz = str((request.cookies or {}).get("ft_tz") or "").strip()
        if cookie_tz:
            tz_name = cookie_tz
    except Exception:
        tz_name = DEFAULT_TZ

    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def utc_to_local(dt, user_tz: ZoneInfo):
    """
    Convert UTC datetime → user timezone.
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(user_tz)


def parse_user_date(value: str | None) -> date | None:
    """Accept ISO (YYYY-MM-DD) or India display (DD/MM/YYYY, DD-MM-YYYY)."""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def local_date_range_to_utc(date_from: str, date_to: str, user_tz: ZoneInfo):
    """
    Convert local date range → UTC datetime range.
    """
    start_day = parse_user_date(date_from)
    end_day = parse_user_date(date_to)
    if start_day is None or end_day is None:
        raise ValueError("Invalid date range")
    start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=user_tz)
    end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=user_tz)

    return (
        start.astimezone(timezone.utc),
        end.astimezone(timezone.utc),
    )


# ------------------------------------------------------
# TEMPLATE HELPERS
# ------------------------------------------------------

def localtime(dt, request):
    return utc_to_local(dt, get_user_timezone(request))


def datetimeformat(value, fmt="%d %b %Y, %I:%M %p"):
    return value.strftime(fmt) if value else ""


def dateformat(value, fmt="%d %b %Y"):
    return value.strftime(fmt) if value else ""
