import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def check():
    client = AsyncIOMotorClient("mongodb://mongodb:27017")
    db = client["fintracker"]
    m = await db.merchant_memory.count_documents({})
    i = await db.transaction_inbox.count_documents({})
    print(f"merchant_memory: {m}")
    print(f"transaction_inbox: {i}")
    client.close()

asyncio.run(check())
