from fastapi import APIRouter, Depends, Query

from app.routers.deps import get_current_user_valid as get_current_user
from app.services.search import search_fintracker

router = APIRouter()


@router.get("")
async def global_search(
    q: str = Query("", max_length=120),
    user=Depends(get_current_user),
):
    user_id = str(user.get("user_id") or "")
    return await search_fintracker(
        user_id=user_id,
        query=q,
        is_admin=bool(user.get("is_admin")),
    )
