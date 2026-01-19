from fastapi import APIRouter
from app.schemas.recurring_deposit import RecurringDepositCreate

from app.services.recurring_deposit import RecurringDepositService

router = APIRouter(prefix="/recurring-deposits", tags=["Recurring Deposits"])


@router.post("/")
async def create_recurring_deposit(payload: RecurringDepositCreate):
    id = await RecurringDepositService.create(payload)
    return {"id": id}
