import httpx
from functools import lru_cache
from app.core.config import settings

JWKS_URL = (
    f"{settings.KEYCLOAK_URL}/realms/"
    f"{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
)

@lru_cache(maxsize=1)
def get_jwks():
    with httpx.Client(timeout=5.0) as client:
        response = client.get(JWKS_URL)
        response.raise_for_status()
        return response.json()
