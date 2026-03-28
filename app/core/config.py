from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    FT_MONGO_URI: str = "mongodb://localhost"
    FT_MONGO_DB_NAME: str = "fintracker"
    FT_ENV: str = "development"
    FT_KEYCLOAK_URL: str = ""
    FT_KEYCLOAK_REALM: str = ""
    FT_CLIENT_ID: str = ""
    FT_CLIENT_SECRET: str = ""
    FT_KEYCLOAK_ADMIN_ROLES: str = "fintracker-admin,admin"
    FT_KEYCLOAK_ADMIN_GROUPS: str = "/fintracker-admin,fintracker-admin"
    FT_SESSION_SECRET: str = "change-me-before-production"
    FT_SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 30
    FT_APP_NAME: str = "FinTracker"
    FT_APP_VERSION: str = "1.0.0"
    FT_BASE_URL: str = ""
    FT_EXTERNAL_PASSWORD_RESET_URL: str | None = None

    FT_APP_LOGO_URL: str = ""
    FT_APP_TIMEZONE: str = "Asia/Kolkata"
    FT_SUPPORT_EMAIL: str = "support@fintracker.local"
    FT_SUPPORT_PHONE: str = "+1-555-0100"
    FT_MAINTENANCE_MODE: bool = False
    FT_MAINTENANCE_MESSAGE: str = ""

    FT_SMTP_ENABLED: bool = False
    FT_SMTP_HOST: str | None = None
    FT_SMTP_PORT: int | None = None
    FT_SMTP_USERNAME: str | None = None
    FT_SMTP_PASSWORD: str | None = None
    FT_SMTP_FROM: str | None = None
    FT_SMTP_TLS: bool = True

    FT_TELEGRAM_ENABLED: bool = False
    FT_TELEGRAM_BOT_USERNAME: str = ""
    FT_TELEGRAM_BOT_TOKEN: str = ""
    FT_TELEGRAM_WEBHOOK_URL: str = ""
    FT_TELEGRAM_WEBHOOK_SECRET: str = ""
    FT_TELEGRAM_POLLING_ENABLED: bool = False

    FT_PUSH_ENABLED: bool = False
    FT_PUSH_VAPID_PUBLIC_KEY: str = ""
    FT_PUSH_FIREBASE_API_KEY: str = ""
    FT_PUSH_FIREBASE_AUTH_DOMAIN: str = ""
    FT_PUSH_FIREBASE_PROJECT_ID: str = ""
    FT_PUSH_FIREBASE_STORAGE_BUCKET: str = ""
    FT_PUSH_FIREBASE_MESSAGING_SENDER_ID: str = ""
    FT_PUSH_FIREBASE_APP_ID: str = ""
    FT_PUSH_FIREBASE_MEASUREMENT_ID: str = ""
    FT_PUSH_FIREBASE_SERVICE_ACCOUNT_JSON: str = ""

    FT_AUTH_ENABLED: bool = True
    FT_AUTH_PROVIDER: str = "keycloak"
    FT_AUTH_ALLOW_LOCAL_LOGIN: bool = True

    FT_DB_ENABLED: bool = True

    FT_BACKUP_ENABLED: bool = False
    FT_BACKUP_PROVIDER: str = "filesystem"
    FT_BACKUP_SCHEDULE_TIME: str = "02:00"
    FT_BACKUP_SCHEDULE_CRON: str = "0 2 * * *"
    FT_BACKUP_RETENTION_DAYS: str = "7"
    FT_BACKUP_DESTINATION: str = "/backups/fintrack"

    FT_LOG_LEVEL: str = "INFO"
    FT_DEBUG_LOG: bool = False
    FT_LOG_DIR: str = "logs"
    FT_LOG_FILE: str = "logs/app.log"

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore",
        env_prefix="",
        env_ignore_empty=True,
    )

    @property
    def is_production(self) -> bool:
        return self.FT_ENV.lower() in ("prod", "production")

settings = Settings()
