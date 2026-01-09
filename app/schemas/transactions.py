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
