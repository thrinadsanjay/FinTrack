from datetime import timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Kolkata"

def get_user_timezone(request):
    """
    Returns user's timezone as ZoneInfo
    """
    tz_name = request.session.get("timezone", DEFAULT_TZ)
    return ZoneInfo(tz_name)


def utc_to_local(dt, user_tz):
    """
    Convert UTC datetime → user timezone
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(user_tz)

def local_date_range_to_utc(date_from, date_to, user_tz):
    start = datetime.fromisoformat(date_from).replace(tzinfo=user_tz)
    end = datetime.fromisoformat(date_to).replace(tzinfo=user_tz)

    return (
        start.astimezone(timezone.utc),
        end.astimezone(timezone.utc),
    )

def localtime(dt, request):
    user_tz = get_user_timezone(request)
    return utc_to_local(dt, user_tz)

def datetimeformat(value, fmt="%d-%m-%Y %I:%M %p"):
    if value is None:
        return ""
    return value.strftime(fmt)

def dateformat(value, fmt="%d-%m-%Y"):
    if value is None:
        return ""
    return value.strftime(fmt)