from fastapi import APIRouter, Depends, status, Request
from app.routers.deps import get_current_api_user

router = APIRouter()

@router.get("/me")
async def me(user=Depends(get_current_api_user)):
    return user

