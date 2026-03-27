from fastapi import APIRouter, Depends, HTTPException

from app.routers.deps import get_current_user
from app.schemas.recurring_deposit import RecurringDepositCreate

from app.services.recurring_deposit import RecurringDepositService

router = APIRouter()


@router.post("/")
async def create_recurring_deposit(payload: RecurringDepositCreate, user=Depends(get_current_user)):
    user_id = user.get("user_id") or user.get("_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session user")

    await RecurringDepositService.create(
        user_id=user_id,
        account_id=payload.account_id,
        amount=payload.amount,
        tx_type=payload.tx_type,
        mode=payload.mode,
        description=payload.description,
        category=payload.category,
        subcategory=payload.subcategory,
        frequency=payload.frequency,
        interval=payload.interval,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return {"ok": True}
