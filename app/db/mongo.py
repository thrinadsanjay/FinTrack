from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

client = AsyncIOMotorClient(settings.FT_MONGO_URI)
db = client[settings.FT_MONGO_DB_NAME]
