from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

<<<<<<< HEAD
client = AsyncIOMotorClient(settings.FT_MONGO_URI)
db = client[settings.FT_MONGO_DB_NAME]
=======
client = AsyncIOMotorClient(settings.MONGO_URI)
db = client[settings.MONGO_DB_NAME]
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
