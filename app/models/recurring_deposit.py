from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, Field


class RecurringDeposit(BaseModel):
    account_id: str
    amount: float
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "halfyearly", "yearly"]
    start_date: date

    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
