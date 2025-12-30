from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGO_URI: str
    MONGO_DB_NAME: str
    ENV: str 
    KEYCLOAK_URL: str 
    KEYCLOAK_REALM: str 
    KEYCLOAK_CLIENT_ID: str
    SESSION_SECRET: str
    APP_NAME: str
    APP_VERSION: str
    APP_BASE_URL: str

    class Config:
        env_file = ".env"

settings = Settings()
