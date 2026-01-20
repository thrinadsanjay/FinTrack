from fastapi.templating import Jinja2Templates
from app.core.config import settings
from app.core.time import get_user_timezone, utc_to_local, localtime, datetimeformat, dateformat

templates = Jinja2Templates(directory="app/frontend/templates")

templates.env.filters["datetimeformat"] = datetimeformat
templates.env.filters["localtime"] = localtime
templates.env.globals["FT_ENV"] = settings.FT_ENV
templates.env.globals["FT_APP_NAME"] = settings.FT_APP_NAME
templates.env.globals["FT_APP_VERSION"] = settings.FT_APP_VERSION
templates.env.globals["FT_KEYCLOAK_URL"] = settings.FT_KEYCLOAK_URL
templates.env.globals["FT_KEYCLOAK_REALM"] = settings.FT_KEYCLOAK_REALM
templates.env.globals["FT_CLIENT_ID"] = settings.FT_CLIENT_ID

