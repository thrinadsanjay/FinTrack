from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId
from app.models.account import PyObjectId

#AuthProvider = Literal["local", "keycloak"]

class UserInDB(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")

    username: Optional[str] = None
    email: Optional[str] = None

    auth_provider: str  # local | keycloak
    keycloak_id: Optional[str] = None

    is_admin: bool = False
    is_active: bool = True
    must_reset_password: bool = False

    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

