from fastapi.templating import Jinja2Templates
from app.core.config import settings
from app.core.time import get_user_timezone, utc_to_local, localtime, datetimeformat, dateformat

templates = Jinja2Templates(directory="app/frontend/templates")

templates.env.filters["datetimeformat"] = datetimeformat
templates.env.filters["localtime"] = localtime
<<<<<<< HEAD
templates.env.globals["FT_ENV"] = settings.FT_ENV
templates.env.globals["FT_APP_NAME"] = settings.FT_APP_NAME
templates.env.globals["FT_APP_VERSION"] = settings.FT_APP_VERSION
templates.env.globals["FT_KEYCLOAK_URL"] = settings.FT_KEYCLOAK_URL
templates.env.globals["FT_KEYCLOAK_REALM"] = settings.FT_KEYCLOAK_REALM
templates.env.globals["FT_CLIENT_ID"] = settings.FT_CLIENT_ID
=======
templates.env.globals["ENV"] = settings.ENV
templates.env.globals["APP_NAME"] = settings.APP_NAME
templates.env.globals["APP_VERSION"] = settings.APP_VERSION
templates.env.globals["KEYCLOAK_URL"] = settings.KEYCLOAK_URL
templates.env.globals["KEYCLOAK_REALM"] = settings.KEYCLOAK_REALM
templates.env.globals["KEYCLOAK_CLIENT_ID"] = settings.KEYCLOAK_CLIENT_ID
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271

