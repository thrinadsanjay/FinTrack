import httpx
from jose import jwt, JWTError
from functools import lru_cache
from typing import Dict

from app.core.config import settings
from app.core.security import get_http_verify


class KeycloakService:
    """
    Central Keycloak token verification service.
    Handles DEV vs PROD logic, JWKS, and SSL consistently.
    """

    def __init__(self):
        self.realm_url = (
            f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}"
        )
        self.jwks_url = f"{self.realm_url}/protocol/openid-connect/certs"
        self.issuer = self.realm_url
        self.audience = settings.KEYCLOAK_CLIENT_ID
        self.is_prod = settings.ENV.lower() in ("prod", "production")

    # ---------------------------
    # JWKS
    # ---------------------------
    @lru_cache()
    def _get_jwks(self) -> Dict:
        resp = httpx.get(
            self.jwks_url,
            timeout=5,
            verify=get_http_verify(),
        )
        resp.raise_for_status()
        return resp.json()

    # ---------------------------
    # DEV MODE
    # ---------------------------
    def _decode_dev(self, id_token: str) -> Dict:
        if self.is_prod:
            raise RuntimeError("DEV token decoder used in PROD")

        return jwt.decode(
            id_token,
            key=None,
            algorithms=["RS256"],
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_iss": False,
                "verify_at_hash": False,
            },
        )

    # ---------------------------
    # PROD MODE
    # ---------------------------
    def _decode_prod(self, id_token: str) -> Dict:
        jwks = self._get_jwks()

        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")

        key = next((k for k in jwks["keys"] if k["kid"] == kid), None)
        if not key:
            raise JWTError("Public key not found for token")

        return jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            leeway=60,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub"],
                "verify_at_hash": False,
            },
        )

    # ---------------------------
    # PUBLIC API
    # ---------------------------
    def verify_id_token(self, id_token: str) -> Dict:
        """
        Verify ID token based on environment.
        """
        if self.is_prod:
            return self._decode_prod(id_token)
        return self._decode_dev(id_token)


# Singleton instance (important)
keycloak_service = KeycloakService()
