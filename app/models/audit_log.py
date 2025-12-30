from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from bson import ObjectId
from app.models.account import PyObjectId


class AuditLogInDB(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")

    user_id: Optional[PyObjectId] = None
    username: Optional[str] = None
    auth_provider: Optional[str] = None

    action: str
    resource: Optional[str] = None

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    meta: Dict[str, Any] = {}

    timestamp: datetime

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
