import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def check():
    client = AsyncIOMotorClient("mongodb://mongodb:27017")
    db = client["fintracker"]
    
    count = await db.transaction_inbox.count_documents({})
    print(f"transaction_inbox count: {count}")
    
    cursor = db.transaction_inbox.find({}).limit(5)
    print("\nSample keys:")
    i = 0
    async for doc in cursor:
        key = doc.get("cleaned_key", "N/A")
        desc = doc.get("description", "")[:50]
        print(f"  {key:<15} | {desc}")
        i += 1
        if i >= 5:
            break
    
    client.close()

asyncio.run(check())
