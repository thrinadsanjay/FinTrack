# Development 

import jwt

def decode_id_token(id_token: str) -> dict:
    # Dev mode: skip signature validation
    # Prod: validate using JWKS
    return jwt.decode(
        id_token,
        options={
            "verify_signature": False,
            "verify_aud": False,
            "verify_iss": False,
        },
    )

## Production 

import httpx
from jose import jwt, JWTError
from functools import lru_cache
from app.core.config import settings


@lru_cache()
def get_jwks():
    jwks_url = (
        f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
        "/protocol/openid-connect/certs"
    )

    resp = httpx.get(jwks_url, timeout=5)
    resp.raise_for_status()
    return resp.json()


def verify_id_token(id_token: str) -> dict:
    jwks = get_jwks()

    unverified_header = jwt.get_unverified_header(id_token)
    kid = unverified_header.get("kid")

    key = next(
        (k for k in jwks["keys"] if k["kid"] == kid),
        None,
    )

    if not key:
        raise JWTError("Public key not found")

    claims = jwt.decode(
        id_token,
        key,
        algorithms=["RS256"],
        audience=settings.KEYCLOAK_CLIENT_ID,
        issuer=f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}",
        options={
            "require": ["exp", "iat", "iss", "aud", "sub"],
            "verify_at_hash": False,   # 👈 REQUIRED
        },
    )

    return claims
