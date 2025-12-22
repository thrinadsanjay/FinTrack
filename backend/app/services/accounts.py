from app.db.mongo import db

async def create_account(user_id, name: str, balance: int = 0):
    doc = {
        "user_id": user_id,
        "name": name,
        "balance": balance,
    }
    result = await db.accounts.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc
