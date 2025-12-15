from pydantic import BaseModel

class AccountCreate(BaseModel):
    name: str
    balance: float = 0.0

class AccountOut(AccountCreate):
    id: int

    class Config:
        from_attributes = True
