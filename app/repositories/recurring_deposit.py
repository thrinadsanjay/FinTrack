from bson import ObjectId
from app.db.mongo import db
from app.models.recurring_deposit import RecurringDeposit


class RecurringDepositRepository:

    @staticmethod
    async def create(data: RecurringDeposit) -> str:
        result = await db[recurring_deposits].insert_one(
            data.model_dump()
        )
        return str(result.inserted_id)

    @staticmethod
    async def find_active_due(now):
        return db[recurring_deposits].find({
            "active": True,
            "next_run_at": {"$lte": now}
        })

    @staticmethod
    async def mark_run(id: str, next_run_at):
        await db[recurring_deposits].update_one(
            {"_id": ObjectId(id)},
            {"$set": {"last_run_at": next_run_at}}
        )
