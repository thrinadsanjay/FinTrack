from bson import ObjectId
from datetime import datetime, timedelta, date, time
from dateutil.relativedelta import relativedelta
from app.db.mongo import db
from app.models.recurring_deposit import RecurringDeposit
from app.schemas.recurring_deposit import RecurringDepositCreate
from app.repositories.recurring_deposit import RecurringDepositRepository


def calculate_next_run(
    last_run: date | None,
    start_date: date,
    frequency: str,
) -> datetime:
    """
    Calendar-correct recurring schedule calculation.
    """

    base_date = last_run or start_date

    if frequency == "daily":
        return datetime.combine(base_date, datetime.min.time()) + relativedelta(days=1)

    if frequency == "weekly":
        return datetime.combine(base_date, datetime.min.time()) + relativedelta(weeks=1)

    if frequency == "biweekly":
        return datetime.combine(base_date, datetime.min.time()) + relativedelta(weeks=2)

    if frequency == "monthly":
        return datetime.combine(base_date, datetime.min.time()) + relativedelta(months=1)

    if frequency == "quarterly":
        return datetime.combine(base_date, datetime.min.time()) + relativedelta(months=3)

    if frequency == "halfyearly":
        return datetime.combine(base_date, datetime.min.time()) + relativedelta(months=6)

    if frequency == "yearly":
        return datetime.combine(base_date, datetime.min.time()) + relativedelta(years=1)

    raise ValueError(f"Unsupported frequency: {frequency}")


class RecurringDepositService:
    @staticmethod
    async def create(
        *,
        user_id: str,
        account_id: str,
        amount: float,
        frequency: str,
        interval: int,
        start_date: date,
        end_date: date | None,
    ):
        start_dt = datetime.combine(start_date, time.min)

        end_dt = (
            datetime.combine(end_date, time.min)
            if end_date else None
        )

        doc = {
            "user_id": ObjectId(user_id),
            "account_id": ObjectId(account_id),
            "amount": amount,
            "frequency": frequency,
            "interval": interval,
            "start_date": start_dt,         # ✅ datetime
            "end_date": end_dt,             # ✅ datetime | None
            "next_run": calculate_next_run(
                last_run=None,
                start_date=start_date,
                frequency=frequency,
            ),
            "is_active": True,
            "created_at": datetime.utcnow(),  # ✅ datetime
        }

        await db.recurring_deposits.insert_one(doc)
