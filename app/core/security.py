"""
Security utilities.

Responsibilities:
- Password hashing & verification
<<<<<<< HEAD
- FT_ENVironment-aware HTTP TLS verification
=======
- Environment-aware HTTP TLS verification
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271

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
<<<<<<< HEAD
    - Enabled in all other FT_ENVironments
    """
    return settings.FT_ENV.lower() not in ("dev", "development")
=======
    - Enabled in all other environments
    """
    return settings.ENV.lower() not in ("dev", "development")
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
