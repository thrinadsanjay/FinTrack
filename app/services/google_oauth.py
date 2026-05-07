"""
Google OAuth ID token verification service.

Responsibilities:
- Verify Google ID tokens using JWKS
- Handle DEV vs PROD behavior safely
- Centralize Google OAuth token validation
"""

import logging
from functools import lru_cache
from typing import Dict

import httpx
from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import get_http_verify

logger = logging.getLogger(__name__)


class GoogleOAuthService:
    jwks_url = "https://www.googleapis.com/oauth2/v3/certs"
    valid_issuers = {"https://accounts.google.com", "accounts.google.com"}

    def __init__(self):
        self.audience = settings.FT_GOOGLE_CLIENT_ID
        self.is_prod = settings.FT_ENV.lower() in ("prod", "production")

    @lru_cache(maxsize=1)
    def _get_jwks(self) -> Dict:
        try:
            resp = httpx.get(
                self.jwks_url,
                timeout=5,
                verify=get_http_verify(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("Failed to fetch Google JWKS: %s", exc)
            raise JWTError("Unable to fetch Google public keys")

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

    def _decode_prod(self, id_token: str, *, audience: str | None = None) -> Dict:
        jwks = self._get_jwks()
        try:
            header = jwt.get_unverified_header(id_token)
        except JWTError:
            raise JWTError("Invalid JWT header")

        kid = header.get("kid")
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if not key:
            raise JWTError("Public key not found for token")

        last_error: JWTError | None = None
        for issuer in self.valid_issuers:
            try:
                return jwt.decode(
                    id_token,
                    key,
                    algorithms=["RS256"],
                    audience=audience or self.audience,
                    issuer=issuer,
                    options={
                        "require": ["exp", "iat", "iss", "aud", "sub"],
                        "verify_at_hash": False,
                        "leeway": 60,
                    },
                )
            except JWTError as exc:
                last_error = exc

        raise last_error or JWTError("Invalid Google ID token issuer")

    def verify_id_token(self, id_token: str, *, audience: str | None = None) -> Dict:
        try:
            if self.is_prod:
                return self._decode_prod(id_token, audience=audience)
            return self._decode_dev(id_token)
        except JWTError as exc:
            logger.warning("Google token verification failed: %s", exc)
            raise


google_oauth_service = GoogleOAuthService()
