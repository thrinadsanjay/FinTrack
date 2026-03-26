from bson import ObjectId
from datetime import datetime, date, time, timezone
from typing import Optional
from app.db.mongo import db
from app.helpers.recurring_schedule import (
    VALID_FREQUENCIES,
    calculate_next_occurrence,
)
from app.helpers.recurring_rules import (
    compute_next_run_from_now,
    recurring_status_of,
    serialize_recurring_rule,
    status_query,
    to_utc,
)
from app.helpers.notification_payloads import (
    recurring_created_payload,
    recurring_ended_payload,
    recurring_paused_payload,
    recurring_resumed_payload,
    recurring_updated_payload,
)
from app.services.audit import audit_log
from app.services.notifications import upsert_notification
from app.helpers.money import round_money
from app.core.errors import ValidationError, NotFoundError, ConflictError


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
        source_transaction_id: Optional[ObjectId] = None,
    ):
        if not start_date:
            raise ValidationError("Start date is required")
        if frequency not in VALID_FREQUENCIES:
            raise ValidationError("Invalid frequency")
        if end_date and end_date < start_date:
            raise ValidationError("End date cannot be before start date")

        amount = round_money(amount)

        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)

        end_dt = (
            datetime.combine(end_date, time.min)
            if end_date else None
        )

        next_run = calculate_next_occurrence(
            start_date=start_date,
            frequency=frequency,
            include_today=False,
        )
        if end_dt:
            end_dt = to_utc(end_dt)
            if next_run > end_dt:
                raise ValidationError("No future run available within end date")

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
            "next_run": next_run,

            # -----------------------------
            # META
            # -----------------------------
            "source_transaction_id": source_transaction_id,
            "is_active": True,
            "created_at": datetime.utcnow(),
        }

        result = await db.recurring_deposits.insert_one(doc)
        audit_meta = {
            "account_id": account_id,
            "amount": amount,
            "type": tx_type,
            "frequency": frequency,
            "interval": interval,
        }
        if source_transaction_id:
            audit_meta["source_transaction_id"] = str(source_transaction_id)

        await audit_log(
            action="RECURRING_CREATED",
            user={"user_id": str(user_id)},
            meta=audit_meta,
        )

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        await upsert_notification(
            user_id=ObjectId(user_id),
            **recurring_created_payload(
                recurring_id=str(result.inserted_id),
                stamp=stamp,
                tx_type=tx_type,
                amount=amount,
            ),
        )

    @staticmethod
    async def list_user_rules(
        *,
        user_id: str,
        status: str = "all",
    ) -> list[dict]:
        uid = ObjectId(user_id)
        now = datetime.now(timezone.utc)

        query = status_query(user_id=uid, status=status, now=now)

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
            rules.append(serialize_recurring_rule(rule=rule, account=account, now=now))

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
        return serialize_recurring_rule(rule=rule, account=account or {}, now=now)

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
        amount = round_money(amount)
        if amount <= 0:
            raise ValidationError("Amount must be positive")
        if frequency not in VALID_FREQUENCIES:
            raise ValidationError("Invalid frequency")

        uid = ObjectId(user_id)
        rid = ObjectId(recurring_id)
        now = datetime.now(timezone.utc)

        rule = await db.recurring_deposits.find_one({"_id": rid, "user_id": uid})
        if not rule:
            raise NotFoundError("Recurring rule not found")

        if recurring_status_of(rule, now) == "ended":
            raise ConflictError("Ended recurring rules cannot be edited")

        start_date = to_utc(rule.get("start_date"))
        end_dt = datetime.combine(end_date, time.min, tzinfo=timezone.utc) if end_date else None
        if end_dt and start_date and end_dt < start_date:
            raise ValidationError("End date cannot be before start date")

        next_run = to_utc(rule.get("next_run"))
        if rule.get("is_active", True):
            next_run = compute_next_run_from_now(
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

        stamp = now.strftime("%Y%m%d%H%M%S%f")
        await upsert_notification(
            user_id=uid,
            **recurring_updated_payload(
                recurring_id=recurring_id,
                stamp=stamp,
                amount=amount,
                frequency=frequency,
            ),
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
            raise NotFoundError("Recurring rule not found")
        if recurring_status_of(rule, now) == "ended":
            raise ConflictError("Ended recurring rules cannot be paused")

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

        stamp = now.strftime("%Y%m%d%H%M%S%f")
        await upsert_notification(
            user_id=uid,
            **recurring_paused_payload(
                recurring_id=recurring_id,
                stamp=stamp,
                description=rule.get("description", "Recurring transaction"),
            ),
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
            raise NotFoundError("Recurring rule not found")
        if recurring_status_of(rule, now) == "ended":
            raise ConflictError("Ended recurring rules cannot be resumed")

        next_run = compute_next_run_from_now(
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

        stamp = now.strftime("%Y%m%d%H%M%S%f")
        await upsert_notification(
            user_id=uid,
            **recurring_resumed_payload(
                recurring_id=recurring_id,
                stamp=stamp,
                description=rule.get("description", "Recurring transaction"),
                next_run_label=next_run.strftime("%d %b %Y"),
            ),
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
            raise NotFoundError("Recurring rule not found")

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

        stamp = now.strftime("%Y%m%d%H%M%S%f")
        await upsert_notification(
            user_id=uid,
            **recurring_ended_payload(
                recurring_id=recurring_id,
                stamp=stamp,
                description=rule.get("description", "Recurring transaction"),
            ),
        )
