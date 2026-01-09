"""
Read-only access to system categories and subcategories.

Responsibilities:
- Fetch categories by transaction type
- Fetch subcategories for a category

Must NOT:
- Modify data
- Write audit logs
"""

from app.db.mongo import db


async def get_categories_by_type(tx_type: str):
    cursor = db.categories.find(
        {
            "type": tx_type,
            "is_system": True,
        },
        {
            "_id": 0,
            "code": 1,
            "name": 1,
        },
    ).sort("name", 1)

    return await cursor.to_list(length=None)


async def get_subcategories(
    *,
    category_code: str,
    tx_type: str,
):
    category = await db.categories.find_one(
        {
            "code": category_code,
            "type": tx_type,
            "is_system": True,
        },
        {
            "_id": 0,
            "subcategories": 1,
        },
    )

    if not category:
        return None

    return category.get("subcategories", [])
