"""
JSON auth endpoints.
Used by API clients to inspect current user.
"""

from fastapi import APIRouter, Depends
from app.routers.deps import get_current_user

router = APIRouter()


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return user
