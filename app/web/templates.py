from fastapi.templating import Jinja2Templates
from app.core.config import settings

templates = Jinja2Templates(directory="app/frontend/templates")

templates.env.globals["ENV"] = settings.ENV
templates.env.globals["APP_NAME"] = settings.APP_NAME
templates.env.globals["APP_VERSION"] = settings.APP_VERSION
templates.env.globals["KEYCLOAK_URL"] = settings.KEYCLOAK_URL
templates.env.globals["KEYCLOAK_REALM"] = settings.KEYCLOAK_REALM
templates.env.globals["KEYCLOAK_CLIENT_ID"] = settings.KEYCLOAK_CLIENT_ID

