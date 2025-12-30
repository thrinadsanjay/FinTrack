import httpx
import hashlib
from jose import jwt
from cachetools import TTLCache
from app.core.config import settings
from passlib.context import CryptContext


# Keycloak JWKS caching
JWKS_CACHE = TTLCache(maxsize=1, ttl=3600)

def get_jwks():
    if "jwks" in JWKS_CACHE:
        return JWKS_CACHE["jwks"]

    url = (
        f"{settings.KEYCLOAK_URL}/realms/"
        f"{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
    )

    response = httpx.get(url)
    response.raise_for_status()
    JWKS_CACHE["jwks"] = response.json()
    return JWKS_CACHE["jwks"]

# Password hashing

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)