from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.account import Account
from app.services.auth import get_current_user
from app.schemas.account import AccountCreate, AccountOut

router = APIRouter()

@router.post("/", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    account = Account(**payload.dict())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account

@router.get("/")
def list_accounts(user=Depends(get_current_user)):
    return {
        "message": "Authenticated",
        "user_id": user["sub"],
        "email": user.get("email"),
    }