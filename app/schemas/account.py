"""
Account API schemas.

Used for:
- API responses
- Future API request validation

NOT used by Web (HTML forms).
"""

from typing import Optional
from pydantic import BaseModel


class AccountCreate(BaseModel):
    """
    Schema for API-based account creation.
    """
    bank_name: str
    type: str
    balance: float
    name: Optional[str] = None


class AccountOut(BaseModel):
    """
    Schema for returning account data via API.
    """
    id: str
    name: str
    bank_name: str
    type: str
    balance: float
