from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    FT_MONGO_URI: str
    FT_MONGO_DB_NAME: str
    FT_ENV: str 
    FT_KEYCLOAK_URL: str 
    FT_KEYCLOAK_REALM: str 
    FT_CLIENT_ID: str
    FT_KEYCLOAK_ADMIN_ROLES: str = "fintracker-admin,admin"
    FT_KEYCLOAK_ADMIN_GROUPS: str = "/fintracker-admin,fintracker-admin"
    FT_SESSION_SECRET: str
    FT_SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 30
    FT_APP_NAME: str
    FT_APP_VERSION: str
    FT_BASE_URL: str
    FT_EXTERNAL_PASSWORD_RESET_URL: str | None = None
    FT_SUPPORT_EMAIL: str = "support@fintracker.local"
    FT_SUPPORT_PHONE: str = "+1-555-0100"
    FT_SMTP_HOST: str | None = None
    FT_SMTP_PORT: int | None = None
    FT_SMTP_USERNAME: str | None = None
    FT_SMTP_FROM: str | None = None
    FT_SMTP_TLS: bool = True
    FT_LOG_LEVEL: str = "INFO"
    FT_DEBUG_LOG: bool = False
    FT_LOG_DIR: str = "logs"
    FT_LOG_FILE: str = "logs/app.log"

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore",
        env_prefix="",
    )

    @property
    def is_production(self) -> bool:
        return self.FT_ENV.lower() in ("prod", "production")

settings = Settings()
