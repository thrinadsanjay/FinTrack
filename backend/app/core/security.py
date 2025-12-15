import httpx
from jose import jwt
from cachetools import TTLCache
from app.core.config import settings

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
