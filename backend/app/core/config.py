from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str 
    ENV: str 
    KEYCLOAK_URL: str 
    KEYCLOAK_REALM: str 
    KEYCLOAK_CLIENT_ID: str

    class Config:
        env_file = ".env"

settings = Settings()
