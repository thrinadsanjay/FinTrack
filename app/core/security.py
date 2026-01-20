"""
Security utilities.

Responsibilities:
- Password hashing & verification
- FT_ENVironment-aware HTTP TLS verification

Must NOT:
- Fetch JWKS
- Handle OAuth logic
- Perform HTTP requests
"""

from passlib.context import CryptContext
from app.core.config import settings


# ======================================================
# PASSWORD HASHING
# ======================================================

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    """
    Hash a plain-text password using Argon2.
    """
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a plain-text password against its hash.
    """
    return pwd_context.verify(password, password_hash)


# ======================================================
# HTTP TLS VERIFICATION
# ======================================================

def get_http_verify() -> bool:
    """
    Control TLS certificate verification.

    - Disabled in DEV / DEVELOPMENT
    - Enabled in all other FT_ENVironments
    """
    return settings.FT_ENV.lower() not in ("dev", "development")
