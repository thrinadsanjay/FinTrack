"""
Internal User database model.

Used by:
- services/users.py
- startup admin creation

NOT used directly by routers.
"""

from datetime import datetime
from typing import Optional, Literal

from bson import ObjectId
from pydantic import BaseModel, Field, model_validator

from app.models.base import PyObjectId  # 👈 shared base


AuthProvider = Literal["local", "keycloak"]


class UserInDB(BaseModel):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")

    username: Optional[str] = None
    email: Optional[str] = None

    auth_provider: AuthProvider

    # --------------------------------------------------
    # AUTH-SPECIFIC FIELDS
    # --------------------------------------------------
    password_hash: Optional[str] = None   # required for local users
    keycloak_id: Optional[str] = None     # required for keycloak users

    # --------------------------------------------------
    # FLAGS
    # --------------------------------------------------
    is_admin: bool = False
    is_active: bool = True
    must_reset_password: bool = False

    # --------------------------------------------------
    # TIMESTAMPS
    # --------------------------------------------------
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = None

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------
    @model_validator(mode="after")
    def validate_auth_provider(self):
        if self.auth_provider == "local" and not self.password_hash:
            raise ValueError("Local users must have password_hash")

        if self.auth_provider == "keycloak" and not self.keycloak_id:
            raise ValueError("Keycloak users must have keycloak_id")

        return self

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
