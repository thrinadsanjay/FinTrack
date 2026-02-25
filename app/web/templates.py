from fastapi.templating import Jinja2Templates
from app.core.config import settings
from app.core.csrf import get_csrf_token
from app.core.time import get_user_timezone, utc_to_local, localtime, datetimeformat, dateformat

templates = Jinja2Templates(directory="app/frontend/templates")

templates.env.filters["datetimeformat"] = datetimeformat
templates.env.filters["dateformat"] = dateformat
templates.env.filters["localtime"] = localtime
templates.env.globals["FT_ENV"] = settings.FT_ENV
templates.env.globals["FT_APP_NAME"] = settings.FT_APP_NAME
templates.env.globals["FT_APP_VERSION"] = settings.FT_APP_VERSION
templates.env.globals["FT_KEYCLOAK_URL"] = settings.FT_KEYCLOAK_URL
templates.env.globals["FT_KEYCLOAK_REALM"] = settings.FT_KEYCLOAK_REALM
templates.env.globals["FT_CLIENT_ID"] = settings.FT_CLIENT_ID
templates.env.globals["FT_SMTP_FROM"] = settings.FT_SMTP_FROM
templates.env.globals["FT_SUPPORT_EMAIL"] = settings.FT_SUPPORT_EMAIL
templates.env.globals["FT_SUPPORT_PHONE"] = settings.FT_SUPPORT_PHONE
templates.env.globals["csrf_token"] = get_csrf_token
