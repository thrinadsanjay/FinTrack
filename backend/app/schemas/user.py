from pydantic import BaseModel

class UserOut(BaseModel):
    id: int
    email: str | None
    username: str | None

    class Config:
        from_attributes = True
