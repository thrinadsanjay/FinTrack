from pydantic import BaseModel, Field
from datetime import date
from typing import Literal


class RecurringDepositCreate(BaseModel):
    account_id: str
    amount: float = Field(gt=0)
    tx_type: Literal["credit", "debit"]
    mode: str = "online"
    description: str = ""
    category: dict
    subcategory: dict
    frequency: Literal["daily", "weekly", "biweekly", "monthly", "quarterly", "halfyearly", "yearly"]
    interval: int = 1
    start_date: date
    end_date: date | None = None


class RecurringDepositResponse(BaseModel):
    id: str
    account_id: str
    amount: float
    tx_type: str
    frequency: str
    start_date: date
    is_active: bool
