from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


class AccountBase(BaseModel):
    name: str
    bank_name: str
    type: str
    balance: float


class AccountInDB(AccountBase):
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: PyObjectId
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}

class AccountCreate(BaseModel):
    bank_name: str
    type: str
    balance: float
    name: Optional[str] = None


class AccountUpdate(BaseModel):
    name: str
    bank_name: str
    type: str
    balance: float
