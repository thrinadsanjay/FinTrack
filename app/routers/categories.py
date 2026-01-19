"""
JSON API for system categories.
Read-only endpoints.
"""

from fastapi import APIRouter, Query, HTTPException
from app.services.categories import (
    get_categories_by_type,
    get_subcategories,
)

router = APIRouter()


@router.get("")
async def list_categories(
    type: str = Query(..., regex="^(credit|debit|transfer)$"),
):
    categories = await get_categories_by_type(type)

    return {
        "type": type,
        "categories": categories,
    }


@router.get("/{category_code}/subcategories")
async def list_subcategories(
    category_code: str,
    type: str = Query(..., regex="^(credit|debit|transfer)$"),
):
    subcategories = await get_subcategories(
        category_code=category_code,
        tx_type=type,
    )

    if subcategories is None:
        raise HTTPException(status_code=404, detail="Category not found")

    return {
        "category": category_code,
        "subcategories": subcategories,
    }
