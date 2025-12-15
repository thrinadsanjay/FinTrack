from fastapi import APIRouter, Depends
from app.services.auth import get_current_user

router = APIRouter()

@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "sub": user["sub"],
        "email": user.get("email"),
        "preferred_username": user.get("preferred_username"),
        "issuer": user.get("iss"),
    }
