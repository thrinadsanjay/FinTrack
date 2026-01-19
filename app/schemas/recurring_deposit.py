from pydantic import BaseModel, Field
from datetime import date
from typing import Literal


class RecurringDepositCreate(BaseModel):
    account_id: str
    amount: float = Field(gt=0)
    frequency: Literal["daily", "weekly", "biweekly", "monthly", "quarterly", "halfyearly", "yearly"]
    start_date: date


class RecurringDepositResponse(BaseModel):
    id: str
    account_id: str
    amount: float
    frequency: str
    start_date: date
    active: bool
