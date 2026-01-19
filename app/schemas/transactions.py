from pydantic import BaseModel
from datetime import date
from typing import Optional, Literal


class RecurringOptions(BaseModel):
    frequency: Literal[
        "daily", "weekly", "monthly",
        "quarterly", "halfyearly", "yearly"
    ]
    start_date: date


class TransactionCreate(BaseModel):
    account_id: str
    amount: float
    transaction_date: date
    type: Literal["deposit", "withdrawal"]

    is_recurring: bool = False
    recurring: Optional[RecurringOptions] = None
