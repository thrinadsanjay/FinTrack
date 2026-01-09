"""
Internal Account database model.

Used by:
- services/accounts.py
- services/transactions.py

NOT used directly by routers.
"""

from datetime import datetime
from bson import ObjectId
from pydantic import BaseModel, Field

from app.models.base import PyObjectId


class AccountInDB(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")

    user_id: PyObjectId
    name: str
    bank_name: str
    type: str
    balance: float

    created_at: datetime
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
