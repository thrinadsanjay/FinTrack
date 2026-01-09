"""
Startup tasks:
- Ensure default admin exists
- Ensure system categories exist
"""

from datetime import datetime
from app.db.mongo import db
from app.services.users import create_local_user
from app.core.setup_vars import (
    SYSTEM_CATEGORIES,
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_EMAIL_ADDRESS,
)


async def ensure_admin_exists() -> bool:
    """
    Create default admin user if missing.
    """
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
        must_reset_password=True,
    )

    return True


async def define_categories():
    """
    Idempotently define system categories.
    """
    for group in SYSTEM_CATEGORIES:
        category_type = group["type"]

        for cat in group["categories"]:
            await db.categories.update_one(
                {"code": cat["code"], "type": category_type},
                {
                    "$set": {
                        "name": cat["name"],
                        "subcategories": cat["subcategories"],
                        "type": category_type,
                        "is_system": True,
                        "updated_at": datetime.utcnow(),
                    },
                    "$setOnInsert": {"created_at": datetime.utcnow()},
                },
                upsert=True,
            )
