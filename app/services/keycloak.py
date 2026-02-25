"""
Keycloak token verification service.

Responsibilities:
- Verify ID tokens using JWKS
- Handle DEV vs PROD behavior safely
- Centralize Keycloak auth logic

Design rules:
- Must NOT raise uncaught exceptions
- Must NOT perform user creation
- Must NOT access sessions
"""

import httpx
import logging
from jose import jwt, JWTError
from functools import lru_cache
from typing import Dict

from app.core.config import settings
from app.core.security import get_http_verify

logger = logging.getLogger(__name__)


class KeycloakService:
    """
    Central Keycloak token verification service.

    Handles:
    - JWKS retrieval and caching
    - DEV vs PROD verification
    - Audience / issuer validation
    """

    def __init__(self):
        self.realm_url = (
            f"{settings.FT_KEYCLOAK_URL}/realms/{settings.FT_KEYCLOAK_REALM}"
        )
        self.jwks_url = f"{self.realm_url}/protocol/openid-connect/certs"
        self.issuer = self.realm_url
        self.audience = settings.FT_CLIENT_ID
        self.is_prod = settings.FT_ENV.lower() in ("prod", "production")

    # ======================================================
    # JWKS (CACHED)
    # ======================================================

    @lru_cache(maxsize=1)
    def _get_jwks(self) -> Dict:
        """
        Fetch and cache JWKS keys.

        NOTE:
        - Cached indefinitely (process lifetime)
        - Safe because Keycloak rotates keys infrequently
        - Restart app to refresh manually
        """
        try:
            resp = httpx.get(
                self.jwks_url,
                timeout=5,
                verify=get_http_verify(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Failed to fetch Keycloak JWKS: %s", exc)
            raise JWTError("Unable to fetch Keycloak public keys")

    # ======================================================
    # DEV MODE (NO SIGNATURE VERIFICATION)
    # ======================================================

    def _decode_dev(self, id_token: str) -> Dict:
        """
        Decode token without verification.
        STRICTLY for non-production FT_ENVironments.
        """
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

    # ======================================================
    # PROD MODE (FULL VERIFICATION)
    # ======================================================

    def _decode_prod(self, id_token: str) -> Dict:
        jwks = self._get_jwks()

        try:
            header = jwt.get_unverified_header(id_token)
        except JWTError:
            raise JWTError("Invalid JWT header")

        kid = header.get("kid")
        key = next((k for k in jwks.get("keys", []) if k["kid"] == kid), None)

        if not key:
            raise JWTError("Public key not found for token")

        return jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub"],
                "verify_at_hash": False,
                # python-jose expects leeway inside options, not as a top-level arg.
                "leeway": 60,
            },
        )

    # ======================================================
    # PUBLIC API
    # ======================================================

    def verify_id_token(self, id_token: str) -> Dict:
        """
        Verify an ID token and return decoded claims.

        Raises:
        - JWTError on invalid token
        """
        try:
            if self.is_prod:
                return self._decode_prod(id_token)
            return self._decode_dev(id_token)
        except JWTError as exc:
            logger.warning("Keycloak token verification failed: %s", exc)
            raise

keycloak_service = KeycloakService()
