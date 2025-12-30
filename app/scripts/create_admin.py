from datetime import datetime
from app.db.mongo import db
from app.services.users import create_local_user

DEFAULT_ADMIN_USERNAME = "admintmp"
DEFAULT_ADMIN_PASSWORD = "admin123"   # TEMP / ONE-TIME
DEFAULT_EMAIL_ADDRESS = "admintmp@example.com"

async def ensure_admin_exists():
    existing = await db.users.find_one({
        "username": DEFAULT_ADMIN_USERNAME,
        "auth_provider": "local",
    })

    if existing:
        return False

    await create_local_user(
        username=DEFAULT_ADMIN_USERNAME,
        password=DEFAULT_ADMIN_PASSWORD,
        email=DEFAULT_EMAIL_ADDRESS,
        is_admin=True,
        must_reset_password=True,   # 👈 FORCE RESET
    )

    return True
