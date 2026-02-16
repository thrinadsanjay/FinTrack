from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    FT_MONGO_URI: str
    FT_MONGO_DB_NAME: str
    FT_ENV: str 
    FT_KEYCLOAK_URL: str 
    FT_KEYCLOAK_REALM: str 
    FT_CLIENT_ID: str
    FT_SESSION_SECRET: str
    FT_APP_NAME: str
    FT_APP_VERSION: str
    FT_BASE_URL: str
    FT_EXTERNAL_PASSWORD_RESET_URL: str | None = None
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
