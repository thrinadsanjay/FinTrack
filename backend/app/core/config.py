from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGO_URI: str
    MONGO_DB_NAME: str
    ENV: str 
    KEYCLOAK_URL: str 
    KEYCLOAK_REALM: str 
    KEYCLOAK_CLIENT_ID: str

    class Config:
        env_file = ".env"

settings = Settings()
