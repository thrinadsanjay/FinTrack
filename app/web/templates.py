from fastapi.templating import Jinja2Templates
from app.core.config import settings
from app.core.csrf import get_csrf_token
from app.core.time import get_user_timezone, utc_to_local, localtime, dateformat
from app.helpers.money import format_inr_digits
from app.helpers.labels import health_band_label, payment_mode_label
from app.helpers.flash import pop_flash
from app.helpers.goal_prompt import pop_goal_prompt
from app.helpers.phone import PHONE_COUNTRIES, DEFAULT_PHONE_COUNTRY, timezone_from_country_iso
from datetime import date as date_cls, datetime as datetime_cls
from zoneinfo import ZoneInfo
from app.core.time import DEFAULT_TZ
from markupsafe import Markup
import json
from jinja2 import Undefined, pass_context


templates = Jinja2Templates(directory="app/frontend/templates")
if not settings.is_production:
    # Dev: pick up template edits (and the bind-mounted app/) without restarts.
    templates.env.auto_reload = True
else:
    # Prod: compile each template once and keep it cached.
    templates.env.auto_reload = False


def money(value) -> str:
    if value is None or isinstance(value, Undefined):
        return "0.00"
    return format_inr_digits(value)


def tojson_filter(value) -> Markup:
    return Markup(json.dumps(value, default=str).replace("<", "\\u003c"))


def _request_tz(context=None):
    request = context.get("request") if context else None
    if request is not None:
        return get_user_timezone(request)
    return ZoneInfo(DEFAULT_TZ)


def _as_local(value, tz):
    if value is None or isinstance(value, Undefined):
        return None
    if isinstance(value, datetime_cls):
        return utc_to_local(value, tz)
    return value


@pass_context
def datetimeformat_filter(context, value, fmt="%d %b %Y, %I:%M %p"):
    local = _as_local(value, _request_tz(context))
    return local.strftime(fmt) if local else ""


@pass_context
def dateformat_filter(context, value, fmt="%d %b %Y"):
    if value is None or isinstance(value, Undefined):
        return ""
    if isinstance(value, datetime_cls):
        value = utc_to_local(value, _request_tz(context))
    elif not isinstance(value, date_cls):
        try:
            value = datetime_cls.fromisoformat(str(value)[:10]).date()
        except Exception:
            return ""
    try:
        return value.strftime(fmt)
    except Exception:
        return dateformat(value, fmt)


def _days_until_value(value, tz):
    if value is None or isinstance(value, Undefined):
        return None
    day = None
    if isinstance(value, datetime_cls):
        local = utc_to_local(value, tz)
        day = local.date() if local else None
    elif isinstance(value, date_cls):
        day = value
    else:
        try:
            day = datetime_cls.fromisoformat(str(value)[:10]).date()
        except Exception:
            return None
    if day is None:
        return None
    return (day - datetime_cls.now(tz).date()).days


@pass_context
def days_until(context, value):
    return _days_until_value(value, _request_tz(context))


@pass_context
def relative_due(context, value) -> str:
    delta = _days_until_value(value, _request_tz(context))
    if delta is None:
        return ""
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta > 1:
        return f"In {delta} days"
    return "Overdue"


templates.env.filters["datetimeformat"] = datetimeformat_filter
templates.env.filters["dateformat"] = dateformat_filter
templates.env.filters["localtime"] = localtime
templates.env.filters["money"] = money
templates.env.filters["mode_label"] = payment_mode_label
templates.env.filters["health_label"] = health_band_label
templates.env.filters["tojson"] = tojson_filter
templates.env.filters["days_until"] = days_until
templates.env.filters["relative_due"] = relative_due
templates.env.globals["FT_ENV"] = settings.FT_ENV
templates.env.globals["FT_APP_NAME"] = settings.FT_APP_NAME
templates.env.globals["FT_APP_VERSION"] = settings.FT_APP_VERSION
templates.env.globals["FT_GOOGLE_CLIENT_ID"] = settings.FT_GOOGLE_CLIENT_ID
templates.env.globals["FT_SMTP_FROM"] = settings.FT_SMTP_FROM
templates.env.globals["FT_SUPPORT_EMAIL"] = settings.FT_SUPPORT_EMAIL
templates.env.globals["FT_SUPPORT_PHONE"] = settings.FT_SUPPORT_PHONE
templates.env.globals["csrf_token"] = get_csrf_token
templates.env.globals["pop_flash"] = pop_flash
templates.env.globals["pop_goal_prompt"] = pop_goal_prompt
templates.env.globals["PHONE_COUNTRIES"] = PHONE_COUNTRIES
templates.env.globals["DEFAULT_PHONE_COUNTRY"] = DEFAULT_PHONE_COUNTRY
templates.env.globals["country_timezone_from_iso"] = timezone_from_country_iso
