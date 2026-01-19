<<<<<<< HEAD
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
=======
"""
Transaction-related API schemas.

Used for:
- Recurring transaction creation via API
- Future scheduler integrations

NOT used directly by Web (HTML forms).
"""

from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class RecurringTransactionCreate(BaseModel):
    """
    Schema for creating a recurring transaction.
    """
    amount: float
    tx_type: str  # credit / debit

    category_code: str
    subcategory_code: str

    description: Optional[str] = None

    # -----------------------------
    # Recurrence rules
    # -----------------------------
    frequency: str          # daily / weekly / monthly / yearly
    interval: int = Field(default=1, ge=1)

    start_date: date
    end_date: Optional[date] = None

    auto_post: bool = True
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
