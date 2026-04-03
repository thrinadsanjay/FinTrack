from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional, Any

from pydantic import BaseModel, Field


CardStatus = Literal["active", "disabled", "closed"]
TxnType = Literal[
    "purchase",
    "refund",
    "reversal",
    "payment",
    "fee",
    "late_fee",
    "interest",
    "gst",
    "bill_adjustment",
    "emi_component",
]
BillPaymentStatus = Literal["unpaid", "partial", "paid", "overdue"]
EmiScheduleType = Literal["reducing", "flat"]


class CreditCardCreate(BaseModel):
    card_name: str = Field(min_length=2, max_length=120)
    bank_name: Optional[str] = Field(default=None, max_length=120)
    network: str = Field(default="visa", max_length=32)
    total_limit: Decimal = Field(gt=0)
    billing_cycle_start_day: int = Field(ge=1, le=31)
    billing_cycle_end_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)
    statement_generation_mode: str = Field(default="auto", max_length=24)
    last4: Optional[str] = Field(default=None, max_length=4)


class CreditCardUpdate(BaseModel):
    card_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    bank_name: Optional[str] = Field(default=None, max_length=120)
    network: Optional[str] = Field(default=None, max_length=32)
    total_limit: Optional[Decimal] = Field(default=None, gt=0)
    billing_cycle_start_day: Optional[int] = Field(default=None, ge=1, le=31)
    billing_cycle_end_day: Optional[int] = Field(default=None, ge=1, le=31)
    due_day: Optional[int] = Field(default=None, ge=1, le=31)
    status: Optional[CardStatus] = None
    last4: Optional[str] = Field(default=None, max_length=4)


class CreditCardTransactionCreate(BaseModel):
    txn_type: TxnType = "purchase"
    amount: Decimal = Field(gt=0)
    txn_date: date
    posted_date: Optional[date] = None
    category: Optional[str] = Field(default=None, max_length=64)
    merchant: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = Field(default=None, max_length=256)
    is_emi: bool = False
    emi_details: Optional[dict[str, Any]] = None
    source: str = Field(default="manual", max_length=24)
    status: str = Field(default="posted", max_length=24)


class CreditCardTransactionUpdate(BaseModel):
    txn_type: Optional[TxnType] = None
    amount: Optional[Decimal] = Field(default=None, gt=0)
    txn_date: Optional[date] = None
    posted_date: Optional[date] = None
    category: Optional[str] = Field(default=None, max_length=64)
    merchant: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = Field(default=None, max_length=256)
    is_emi: Optional[bool] = None
    emi_details: Optional[dict[str, Any]] = None
    source: Optional[str] = Field(default=None, max_length=24)
    status: Optional[str] = Field(default=None, max_length=24)


class CreditBillUpdate(BaseModel):
    final_amount: Optional[Decimal] = Field(default=None, ge=0)
    minimum_due: Optional[Decimal] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=280)


class CreditBillPaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_date: date
    source_account_id: Optional[str] = None
    payment_mode: str = Field(default="bank_transfer", max_length=48)
    reference_no: Optional[str] = Field(default=None, max_length=120)


class CreditEmiCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    principal: Decimal = Field(gt=0)
    interest_rate_annual: Decimal = Field(ge=0)
    tenure_months: int = Field(gt=0, le=120)
    start_date: date
    gst_rate: Decimal = Field(default=Decimal("18.0"), ge=0)
    schedule_type: EmiScheduleType = "reducing"
    source_transaction_id: Optional[str] = None


class CreditEmiUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=120)
    interest_rate_annual: Optional[Decimal] = Field(default=None, ge=0)
    tenure_months: Optional[int] = Field(default=None, gt=0, le=120)
    gst_rate: Optional[Decimal] = Field(default=None, ge=0)
    status: Optional[str] = Field(default=None, max_length=24)


class CreditCardOut(BaseModel):
    id: str
    user_id: str
    card_name: str
    bank_name: Optional[str] = None
    network: str
    last4: Optional[str] = None
    total_limit: float
    available_limit: float
    billing_cycle_start_day: int
    billing_cycle_end_day: int
    due_day: int
    statement_generation_mode: str
    status: str
    created_at: datetime
    updated_at: datetime


class CreditCardSummaryOut(BaseModel):
    total_cards: int
    total_limit: float
    total_outstanding: float
    total_statement_due: float
    utilization_percent: float
    upcoming_due_count: int
    active_emi_count: int


class LiabilityForecastRow(BaseModel):
    cycle_key: str
    projected_bill_amount: float
    projected_emi_amount: float
    projected_due_date: Optional[datetime] = None
