from pydantic_settings import BaseSettings, Field
from app.db.base import Base


class User(BaseModel):
    id: ObjectId = Field(alias="_id")
    keycloak_id: str
    email: str | None = None
    username: str | None = None

    class Config:
        arbitrary_types_allowed = True
