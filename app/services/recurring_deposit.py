from bson import ObjectId
from datetime import datetime, date, time, timezone
from dateutil.relativedelta import relativedelta
from app.db.mongo import db
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

    @staticmethod
    def _to_utc(dt: datetime | None) -> datetime | None:
        if not dt:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _status_of(rule: dict, now: datetime) -> str:
        ended_at = RecurringDepositService._to_utc(rule.get("ended_at"))
        end_date = RecurringDepositService._to_utc(rule.get("end_date"))
        if ended_at:
            return "ended"
        if end_date and end_date < now:
            return "ended"
        if rule.get("is_active", True):
            return "active"
        return "paused"

    @staticmethod
    def _compute_next_run_from_now(*, rule: dict, frequency: str, now: datetime) -> datetime:
        start_date = rule.get("start_date")
        if not start_date:
            raise Exception("Recurring rule is missing start date")
        start_date = RecurringDepositService._to_utc(start_date)

        candidate = RecurringDepositService._to_utc(rule.get("next_run"))
        if not candidate:
            candidate = datetime.combine(start_date.date(), time.min, tzinfo=timezone.utc)

        # Bring schedule forward so we don't create delayed backlogs on resume/edit.
        guard = 0
        while candidate <= now and guard < 1000:
            candidate = calculate_next_run(
                last_run=candidate.date(),
                start_date=start_date.date(),
                frequency=frequency,
            )
            candidate = RecurringDepositService._to_utc(candidate)
            guard += 1

        return candidate

    @staticmethod
    async def list_user_rules(
        *,
        user_id: str,
        status: str = "all",
    ) -> list[dict]:
        uid = ObjectId(user_id)
        now = datetime.now(timezone.utc)

        query: dict = {"user_id": uid}

        if status == "active":
            query.update(
                {
                    "is_active": True,
                    "$or": [
                        {"end_date": None},
                        {"end_date": {"$gte": now}},
                    ],
                    "ended_at": None,
                }
            )
        elif status == "paused":
            query.update(
                {
                    "is_active": False,
                    "ended_at": None,
                    "$or": [
                        {"end_date": None},
                        {"end_date": {"$gte": now}},
                    ],
                }
            )
        elif status == "ended":
            query.update(
                {
                    "$or": [
                        {"ended_at": {"$ne": None}},
                        {"end_date": {"$lt": now}},
                    ]
                }
            )

        cursor = db.recurring_deposits.find(query).sort("created_at", -1)
        account_cursor = db.accounts.find(
            {"user_id": uid, "deleted_at": None},
            {"name": 1, "bank_name": 1},
        )

        account_map: dict[str, dict] = {}
        async for acc in account_cursor:
            account_map[str(acc["_id"])] = {
                "name": acc.get("name") or "Account",
                "bank_name": acc.get("bank_name") or "",
            }

        rules: list[dict] = []
        async for rule in cursor:
            account_id = str(rule.get("account_id"))
            account = account_map.get(account_id, {})
            next_run = RecurringDepositService._to_utc(rule.get("next_run"))
            end_date = RecurringDepositService._to_utc(rule.get("end_date"))
            ended_at = RecurringDepositService._to_utc(rule.get("ended_at"))
            status_value = RecurringDepositService._status_of(rule, now)

            rules.append(
                {
                    "id": str(rule["_id"]),
                    "account_id": account_id,
                    "account_name": account.get("name", "Account"),
                    "bank_name": account.get("bank_name", ""),
                    "type": rule.get("type"),
                    "mode": rule.get("mode"),
                    "amount": rule.get("amount", 0),
                    "description": rule.get("description", ""),
                    "category": rule.get("category", {}),
                    "subcategory": rule.get("subcategory", {}),
                    "frequency": rule.get("frequency"),
                    "interval": rule.get("interval", 1),
                    "start_date": RecurringDepositService._to_utc(rule.get("start_date")),
                    "end_date": end_date,
                    "next_run": next_run,
                    "last_run": RecurringDepositService._to_utc(rule.get("last_run")),
                    "is_active": rule.get("is_active", True),
                    "ended_at": ended_at,
                    "created_at": RecurringDepositService._to_utc(rule.get("created_at")),
                    "status": status_value,
                }
            )

        return rules

    @staticmethod
    async def get_user_rule(
        *,
        user_id: str,
        recurring_id: str,
    ) -> dict | None:
        uid = ObjectId(user_id)
        rid = ObjectId(recurring_id)
        now = datetime.now(timezone.utc)
        rule = await db.recurring_deposits.find_one({"_id": rid, "user_id": uid})
        if not rule:
            return None

        account = await db.accounts.find_one(
            {"_id": rule.get("account_id")},
            {"name": 1, "bank_name": 1},
        )
        return {
            "id": str(rule["_id"]),
            "account_id": str(rule.get("account_id")),
            "account_name": (account or {}).get("name", "Account"),
            "bank_name": (account or {}).get("bank_name", ""),
            "type": rule.get("type"),
            "mode": rule.get("mode"),
            "amount": rule.get("amount", 0),
            "description": rule.get("description", ""),
            "category": rule.get("category", {}),
            "subcategory": rule.get("subcategory", {}),
            "frequency": rule.get("frequency"),
            "interval": rule.get("interval", 1),
            "start_date": RecurringDepositService._to_utc(rule.get("start_date")),
            "end_date": RecurringDepositService._to_utc(rule.get("end_date")),
            "next_run": RecurringDepositService._to_utc(rule.get("next_run")),
            "last_run": RecurringDepositService._to_utc(rule.get("last_run")),
            "is_active": rule.get("is_active", True),
            "ended_at": RecurringDepositService._to_utc(rule.get("ended_at")),
            "status": RecurringDepositService._status_of(rule, now),
        }

    @staticmethod
    async def update_rule(
        *,
        user_id: str,
        recurring_id: str,
        amount: float,
        description: str,
        frequency: str,
        end_date: date | None,
        request=None,
    ):
        if amount <= 0:
            raise Exception("Amount must be positive")

        uid = ObjectId(user_id)
        rid = ObjectId(recurring_id)
        now = datetime.now(timezone.utc)

        rule = await db.recurring_deposits.find_one({"_id": rid, "user_id": uid})
        if not rule:
            raise Exception("Recurring rule not found")

        if RecurringDepositService._status_of(rule, now) == "ended":
            raise Exception("Ended recurring rules cannot be edited")

        start_date = RecurringDepositService._to_utc(rule.get("start_date"))
        end_dt = datetime.combine(end_date, time.min, tzinfo=timezone.utc) if end_date else None
        if end_dt and start_date and end_dt < start_date:
            raise Exception("End date cannot be before start date")

        next_run = RecurringDepositService._to_utc(rule.get("next_run"))
        if rule.get("is_active", True):
            next_run = RecurringDepositService._compute_next_run_from_now(
                rule=rule,
                frequency=frequency,
                now=now,
            )
            if end_dt and next_run > end_dt:
                rule["is_active"] = False

        update_doc = {
            "amount": amount,
            "description": description.strip(),
            "frequency": frequency,
            "end_date": end_dt,
            "updated_at": now,
            "next_run": next_run,
            "is_active": rule.get("is_active", True),
        }

        await db.recurring_deposits.update_one(
            {"_id": rid, "user_id": uid},
            {"$set": update_doc},
        )

        await audit_log(
            action="RECURRING_UPDATED",
            request=request,
            user={"user_id": user_id},
            meta={
                "recurring_id": recurring_id,
                "amount": amount,
                "frequency": frequency,
                "end_date": end_date.isoformat() if end_date else None,
            },
        )

    @staticmethod
    async def pause_rule(
        *,
        user_id: str,
        recurring_id: str,
        request=None,
    ):
        uid = ObjectId(user_id)
        rid = ObjectId(recurring_id)
        now = datetime.now(timezone.utc)

        rule = await db.recurring_deposits.find_one({"_id": rid, "user_id": uid})
        if not rule:
            raise Exception("Recurring rule not found")
        if RecurringDepositService._status_of(rule, now) == "ended":
            raise Exception("Ended recurring rules cannot be paused")

        await db.recurring_deposits.update_one(
            {"_id": rid, "user_id": uid},
            {
                "$set": {
                    "is_active": False,
                    "paused_at": now,
                    "updated_at": now,
                }
            },
        )

        await audit_log(
            action="RECURRING_PAUSED",
            request=request,
            user={"user_id": user_id},
            meta={"recurring_id": recurring_id},
        )

    @staticmethod
    async def resume_rule(
        *,
        user_id: str,
        recurring_id: str,
        request=None,
    ):
        uid = ObjectId(user_id)
        rid = ObjectId(recurring_id)
        now = datetime.now(timezone.utc)

        rule = await db.recurring_deposits.find_one({"_id": rid, "user_id": uid})
        if not rule:
            raise Exception("Recurring rule not found")
        if RecurringDepositService._status_of(rule, now) == "ended":
            raise Exception("Ended recurring rules cannot be resumed")

        next_run = RecurringDepositService._compute_next_run_from_now(
            rule=rule,
            frequency=rule.get("frequency"),
            now=now,
        )

        await db.recurring_deposits.update_one(
            {"_id": rid, "user_id": uid},
            {
                "$set": {
                    "is_active": True,
                    "next_run": next_run,
                    "resumed_at": now,
                    "updated_at": now,
                }
            },
            upsert=False,
        )

        await audit_log(
            action="RECURRING_RESUMED",
            request=request,
            user={"user_id": user_id},
            meta={"recurring_id": recurring_id, "next_run": next_run.isoformat()},
        )

    @staticmethod
    async def end_rule(
        *,
        user_id: str,
        recurring_id: str,
        request=None,
    ):
        uid = ObjectId(user_id)
        rid = ObjectId(recurring_id)
        now = datetime.now(timezone.utc)

        rule = await db.recurring_deposits.find_one({"_id": rid, "user_id": uid})
        if not rule:
            raise Exception("Recurring rule not found")

        await db.recurring_deposits.update_one(
            {"_id": rid, "user_id": uid},
            {
                "$set": {
                    "is_active": False,
                    "ended_at": now,
                    "end_date": now,
                    "updated_at": now,
                }
            },
            upsert=False,
        )

        await audit_log(
            action="RECURRING_ENDED",
            request=request,
            user={"user_id": user_id},
            meta={"recurring_id": recurring_id},
        )
