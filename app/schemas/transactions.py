from pydantic import BaseModel, Field
from typing import Optional
from datetime import date
from bson import ObjectId

class RecurringTransactionCreate(BaseModel):
    name: str
    amount: float
    category_id: str
    transaction_type: str  # debit / credit

    frequency: str         # daily / weekly / monthly / yearly
    interval: int = 1
    start_date: date
    end_date: Optional[date] = None
    auto_post: bool = True

class RecurringTransactionDB(RecurringTransactionCreate):
    id: ObjectId = Field(alias="_id")
    user_id: str
    next_run: date
    last_run: Optional[date] = None
    is_active: bool = True
