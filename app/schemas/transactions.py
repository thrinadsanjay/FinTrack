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
"""
Transaction-related API schemas.

Used for:
- Recurring transaction creation via API
- Future scheduler integrations

NOT used directly by Web (HTML forms).
"""

from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


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


class TransactionCreateRequest(BaseModel):
    """POST /api/transactions: same capabilities as the web add form."""

    account_id: str
    amount: float = Field(gt=0)
    tx_type: Literal["debit", "credit", "transfer", "card_payment"]
    mode: str = "online"
    category_code: str
    subcategory_code: str
    description: str = ""
    transaction_date: Optional[date] = None

    target_account_id: Optional[str] = None
    credit_bill_id: Optional[str] = None

    is_recurring: bool = False
    frequency: Optional[str] = None
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def _check_shape(self):
        if self.tx_type in {"transfer", "card_payment"} and not self.target_account_id:
            raise ValueError("target_account_id is required for transfers and card payments")
        if self.is_recurring and (not self.frequency or not self.start_date):
            raise ValueError("frequency and start_date are required for recurring transactions")
        return self


class TransactionEditRequest(BaseModel):
    account_id: str
    amount: float = Field(gt=0)
    category_code: str
    subcategory_code: str
    description: str = ""


class EmiConversionRequest(BaseModel):
    tenure_months: int = Field(ge=2)
    interest_rate: float = Field(default=0.0, ge=0)
    processing_fee_rate: float = Field(default=0.0, ge=0)
    title: Optional[str] = None
