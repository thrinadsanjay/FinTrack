from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ChatLog(BaseModel):
    user_id: str
    sender: str  # "user" | "bot" | "admin"
    message: str
    timestamp: datetime
    read: bool = False
    resolved: bool = False