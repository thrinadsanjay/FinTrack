"""
User API response schema.

Used by:
- routers/auth.py (/me)
- future user-related APIs

Not used for user creation or updates.
"""

from pydantic import BaseModel
from typing import Optional


class UserOut(BaseModel):
    id: str
    email: Optional[str] = None
    username: Optional[str] = None
