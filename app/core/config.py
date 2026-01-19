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

    model_config = ConfigDict(
        FT_ENV_file=".FT_ENV",
        extra="ignore",   # 👈 THIS fixes your error
        FT_ENV_prefix="FT_",
    )

settings = Settings()
