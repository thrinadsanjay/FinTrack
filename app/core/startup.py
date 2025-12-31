from datetime import datetime
from app.db.mongo import db
from app.services.users import create_local_user
from app.core.setup_vars import SYSTEM_CATEGORIES, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, DEFAULT_EMAIL_ADDRESS


# Create a default admin user if none exists

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

# Create Categories and Sub-categories

async def define_categories():
    for group in SYSTEM_CATEGORIES:
        category_type = group["type"]   # credit / debit / transfer

        for cat in group["categories"]:
            await db.categories.update_one(
                {
                    "code": cat["code"],
                    "type": category_type,
                },
                {
                    "$set": {
                        "name": cat["name"],
                        "subcategories": cat["subcategories"],
                        "type": category_type,
                        "is_system": True,              # ✅ ALWAYS enforce
                        "updated_at": datetime.utcnow(),
                    },
                    "$setOnInsert": {
                        "created_at": datetime.utcnow(),
                    },
                },
                upsert=True,
            )
