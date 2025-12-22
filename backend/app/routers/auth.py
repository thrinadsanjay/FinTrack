from fastapi import APIRouter, Depends, status, Request
from app.services.auth import get_current_user
from app.services.audit import create_audit_log

router = APIRouter()

@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(
    request: Request,
    user=Depends(get_current_user),
):
    await create_audit_log(
        user=user,
        action="user_login",
        resource="auth",
        request=request,
    )

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    user=Depends(get_current_user),
):
    await create_audit_log(
        user=user,
        action="user_logout",
        resource="auth",
        request=request,
    )
