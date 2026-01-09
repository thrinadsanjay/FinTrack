"""
Internal audit log model.

NOTE:
- Not currently used by services
- Provided for future admin / reporting APIs
"""

from datetime import datetime
from typing import Optional, Dict, Any

from bson import ObjectId
from pydantic import BaseModel, Field

from app.models.base import PyObjectId


class AuditLogInDB(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")

    user_id: Optional[PyObjectId] = None
    username: Optional[str] = None
    auth_provider: Optional[str] = None

    action: str

    ip: Optional[str] = None
    user_agent: Optional[str] = None

    meta: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
