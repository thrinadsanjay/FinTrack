from fastapi import APIRouter, Query, HTTPException
from app.db.mongo import db

router = APIRouter()

@router.get("")
async def get_categories(
    type: str = Query(..., regex="^(credit|debit|transfer)$"),
):
    cursor = db.categories.find(
        {
            "type": type,
            "is_system": True,
        },
        {
            "_id": 0,
            "code": 1,
            "name": 1,
        },
    ).sort("name", 1)

    categories = await cursor.to_list(length=None)

    return {
        "type": type,
        "categories": categories,
    }

@router.get("/{category_code}/subcategories")
async def get_subcategories(
    category_code: str,
    type: str = Query(..., regex="^(credit|debit|transfer)$"),
):
    category = await db.categories.find_one(
        {
            "code": category_code,
            "type": type,
            "is_system": True,
        },
        {
            "_id": 0,
            "subcategories": 1,
        },
    )

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    return {
        "category": category_code,
        "subcategories": category.get("subcategories", []),
    }
