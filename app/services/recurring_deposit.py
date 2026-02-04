from bson import ObjectId
from datetime import datetime, timedelta, date, time
from dateutil.relativedelta import relativedelta
from app.db.mongo import db
from app.models.recurring_deposit import RecurringDeposit
from app.schemas.recurring_deposit import RecurringDepositCreate
from app.repositories.recurring_deposit import RecurringDepositRepository
from app.services.audit import audit_log


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
        user_id: ObjectId,
        account_id: str,
        amount: float,
        tx_type: str,
        mode: str,
        description: str,
        category: dict,
        subcategory: dict,
        frequency: str,
        interval: int,
        start_date: date,
        end_date: date | None,
        source_transaction_id: ObjectId,
    ):

        start_dt = datetime.combine(start_date, time.min)

        end_dt = (
            datetime.combine(end_date, time.min)
            if end_date else None
        )

        doc = {
            # -----------------------------
            # Ownership
            # -----------------------------
            "user_id": ObjectId(user_id),
            "account_id": ObjectId(account_id),

            # -----------------------------
            # TRANSACTION TEMPLATE ✅
            # -----------------------------
            "type": tx_type,
            "mode": mode,
            "amount": amount,
            "description": description,
            "category": category,           # { code, name }
            "subcategory": subcategory,     # { code, name }

            # -----------------------------
            # SCHEDULE
            # -----------------------------
            "frequency": frequency,
            "interval": interval,
            "start_date": start_dt,
            "end_date": end_dt,
            "next_run": calculate_next_run(
                last_run=None,
                start_date=start_date,
                frequency=frequency,
            ),

            # -----------------------------
            # META
            # -----------------------------
            "source_transaction_id": source_transaction_id,
            "is_active": True,
            "created_at": datetime.utcnow(),
        }

        await db.recurring_deposits.insert_one(doc)
        await audit_log(
            action="RECURRING_CREATED",
            user={"user_id": str(user_id)},
            meta={
                "account_id": account_id,
                "amount": amount,
                "type": tx_type,
                "frequency": frequency,
                "interval": interval,
                "source_transaction_id": str(source_transaction_id),
            },
        )
