from datetime import date

from pydantic import BaseModel, Field


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
    goal_type: str = "custom"
    current_amount: float = 0
    target_date: date | None = None
    linked_account_id: str | None = None
    linked_category_code: str | None = None
    notes: str | None = None
    linked_recurring_ids: list[str] = Field(default_factory=list)
    linked_transaction_ids: list[str] = Field(default_factory=list)


class GoalLinks(BaseModel):
    """Replaces the goal's linked investments."""

    recurring_ids: list[str] = Field(default_factory=list, max_length=100)
    transaction_ids: list[str] = Field(default_factory=list, max_length=100)


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: float | None = Field(default=None, gt=0)
    goal_type: str | None = None
    current_amount: float | None = None
    target_date: date | None = None
    linked_account_id: str | None = None
    linked_category_code: str | None = None
    notes: str | None = None
    status: str | None = None
