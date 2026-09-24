"""Loan account lifecycle: EMI cycles, ledger, interest certificate."""

from __future__ import annotations

from datetime import date, datetime, timezone

from bson import ObjectId
from fastapi import Request

from app.core.errors import NotFoundError, ValidationError
from app.db.mongo import db
from app.helpers.loan_math import apply_emi_cycle, loan_certificate, next_emi_date
from app.helpers.money import round_money
from app.services.audit import audit_log


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _display_date(value) -> str:
    parsed = _as_date(value)
    return parsed.strftime("%d %b %Y") if parsed else (str(value) if value else "—")


def loan_fields(
    *,
    outstanding: float,
    original_principal: float | None,
    interest_rate: float | None,
    emi_amount: float | None,
    emi_day: int | None,
    tenure_months: int | None,
    start_date: date | None,
    interest_paid: float | None = None,
    principal_paid: float | None = None,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    outstanding = round_money(max(float(outstanding or 0), 0))
    original = round_money(original_principal if original_principal not in (None, "") else outstanding)
    rate = round_money(interest_rate or 0)
    emi = round_money(emi_amount or 0)
    day = int(emi_day or today.day)
    if day < 1 or day > 31:
        raise ValidationError("EMI day must be between 1 and 31")
    if rate < 0:
        raise ValidationError("Interest rate cannot be negative")
    if emi < 0:
        raise ValidationError("EMI amount cannot be negative")
    start = start_date or today
    return {
        "balance": outstanding,
        "original_principal": original,
        "interest_rate": rate,
        "emi_amount": emi,
        "emi_day": day,
        "tenure_months": int(tenure_months) if tenure_months else None,
        "start_date": datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
        "interest_paid": round_money(interest_paid or 0),
        "principal_paid": round_money(principal_paid or 0),
        "emis_paid": 0,
        "next_due_date": datetime.combine(next_emi_date(today, day, inclusive=True), datetime.min.time(), tzinfo=timezone.utc),
        "loan_status": "closed" if outstanding <= 0 else "active",
        "last_emi_date": None,
    }


async def apply_loan_cycle(
    *,
    user_id: str,
    account: dict,
    cycle_date: date | None = None,
    request: Request | None = None,
    force: bool = False,
) -> dict | None:
    if str(account.get("type") or "") != "loan":
        return None
    outstanding = round_money(max(float(account.get("balance") or 0), 0))
    if outstanding <= 0:
        return None
    today = cycle_date or date.today()
    next_due = _as_date(account.get("next_due_date"))
    if not force and next_due and next_due > today:
        return None

    used_date = next_due or today
    existing = await db.loan_ledger.find_one(
        {
            "account_id": account["_id"],
            "cycle_date": used_date.isoformat(),
            "deleted_at": None,
        }
    )
    if existing:
        nxt = next_emi_date(used_date, int(account.get("emi_day") or used_date.day), inclusive=False)
        await db.accounts.update_one(
            {"_id": account["_id"]},
            {"$set": {"next_due_date": datetime.combine(nxt, datetime.min.time(), tzinfo=timezone.utc), "updated_at": _now()}},
        )
        return None

    split = apply_emi_cycle(
        outstanding=outstanding,
        emi_amount=account.get("emi_amount") or 0,
        annual_rate=account.get("interest_rate") or 0,
    )
    if split["payment"] <= 0:
        return None

    now = _now()
    nxt = next_emi_date(used_date, int(account.get("emi_day") or used_date.day), inclusive=False)
    updates = {
        "balance": split["outstanding"],
        "interest_paid": round_money(float(account.get("interest_paid") or 0) + split["interest"]),
        "principal_paid": round_money(float(account.get("principal_paid") or 0) + split["principal"]),
        "emis_paid": int(account.get("emis_paid") or 0) + 1,
        "last_emi_date": datetime.combine(used_date, datetime.min.time(), tzinfo=timezone.utc),
        "next_due_date": datetime.combine(nxt, datetime.min.time(), tzinfo=timezone.utc),
        "loan_status": "closed" if split["closed"] else "active",
        "updated_at": now,
    }
    await db.accounts.update_one({"_id": account["_id"]}, {"$set": updates})
    await db.loan_ledger.insert_one(
        {
            "user_id": ObjectId(user_id),
            "account_id": account["_id"],
            "cycle_date": used_date.isoformat(),
            "interest": split["interest"],
            "principal": split["principal"],
            "payment": split["payment"],
            "outstanding_after": split["outstanding"],
            "created_at": now,
            "deleted_at": None,
        }
    )
    await audit_log(
        action="LOAN_EMI_APPLIED",
        request=request,
        user={"user_id": user_id},
        meta={
            "account_id": str(account["_id"]),
            "cycle_date": used_date.isoformat(),
            "interest": split["interest"],
            "principal": split["principal"],
            "payment": split["payment"],
            "outstanding": split["outstanding"],
        },
    )
    account.update(updates)
    return split


async def apply_due_loan_cycles(
    *,
    user_id: str,
    today: date | None = None,
    request: Request | None = None,
    account_id: str | None = None,
) -> int:
    today = today or date.today()
    query = {"user_id": ObjectId(user_id), "type": "loan", "deleted_at": None, "loan_status": {"$ne": "closed"}}
    if account_id:
        query["_id"] = ObjectId(account_id)
    applied = 0
    cursor = db.accounts.find(query)
    async for account in cursor:
        guard = 0
        while guard < 360:
            next_due = _as_date(account.get("next_due_date"))
            if next_due and next_due > today:
                break
            if round_money(account.get("balance") or 0) <= 0:
                break
            result = await apply_loan_cycle(
                user_id=user_id,
                account=account,
                cycle_date=today,
                request=request,
            )
            if not result:
                break
            applied += 1
            guard += 1
    return applied


async def apply_all_due_loans(*, today: date | None = None) -> int:
    today = today or date.today()
    applied = 0
    cursor = db.accounts.find({"type": "loan", "deleted_at": None, "loan_status": {"$ne": "closed"}})
    async for account in cursor:
        user_id = str(account.get("user_id") or "")
        if not user_id:
            continue
        applied += await apply_due_loan_cycles(user_id=user_id, today=today, account_id=str(account["_id"]))
    return applied


async def get_loan_certificate(*, user_id: str, account_id: str) -> dict:
    account = await db.accounts.find_one(
        {"_id": ObjectId(account_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not account:
        raise NotFoundError("Loan not found")
    if account.get("type") != "loan":
        raise ValidationError("Interest certificate is only available for loan accounts")
    ledger = [
        doc
        async for doc in db.loan_ledger.find(
            {"account_id": account["_id"], "deleted_at": None}
        ).sort("cycle_date", 1)
    ]
    cert = loan_certificate(account)
    cert["name"] = account.get("name") or account.get("bank_name") or "Loan"
    cert["bank_name"] = account.get("bank_name")
    cert["ledger"] = [
        {
            "cycle_date": _display_date(row.get("cycle_date")),
            "interest": row.get("interest"),
            "principal": row.get("principal"),
            "payment": row.get("payment"),
            "outstanding_after": row.get("outstanding_after"),
        }
        for row in ledger
    ]
    return cert


async def update_loan_settings(
    *,
    user_id: str,
    account_id: str,
    name: str | None,
    interest_rate: float | None,
    emi_amount: float | None,
    emi_day: int | None,
    tenure_months: int | None,
    last4: str | None = None,
    loan_kind: str | None = None,
    bank_name: str | None = None,
    original_principal: float | None = None,
    outstanding: float | None = None,
    request: Request | None = None,
):
    account = await db.accounts.find_one(
        {"_id": ObjectId(account_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not account:
        raise NotFoundError("Loan not found")
    if account.get("type") != "loan":
        raise ValidationError("Loan settings can only be updated for loan accounts")
    updates = {"updated_at": _now()}
    if name and name.strip():
        updates["name"] = name.strip()
    if interest_rate is not None:
        if interest_rate < 0:
            raise ValidationError("Interest rate cannot be negative")
        updates["interest_rate"] = round_money(interest_rate)
    if emi_amount is not None:
        if emi_amount < 0:
            raise ValidationError("EMI amount cannot be negative")
        updates["emi_amount"] = round_money(emi_amount)
    if emi_day is not None:
        if emi_day < 1 or emi_day > 31:
            raise ValidationError("EMI day must be between 1 and 31")
        updates["emi_day"] = int(emi_day)
        today = date.today()
        nxt = next_emi_date(today, emi_day, inclusive=True)
        updates["next_due_date"] = datetime.combine(nxt, datetime.min.time(), tzinfo=timezone.utc)
    if tenure_months is not None:
        updates["tenure_months"] = int(tenure_months) if tenure_months else None
    if last4 is not None:
        from app.services.accounts import normalize_last4

        updates["last4"] = normalize_last4(last4)
    if loan_kind is not None:
        from app.helpers.accounts_ui import normalize_loan_kind

        updates["loan_kind"] = normalize_loan_kind(loan_kind, name=updates.get("name") or account.get("name"))
    if bank_name is not None and bank_name.strip():
        updates["bank_name"] = bank_name.strip()
    if original_principal is not None:
        if original_principal < 0:
            raise ValidationError("Original principal cannot be negative")
        updates["original_principal"] = round_money(original_principal)
    if outstanding is not None:
        if outstanding < 0:
            raise ValidationError("Outstanding cannot be negative")
        updates["balance"] = round_money(outstanding)
    await db.accounts.update_one({"_id": account["_id"]}, {"$set": updates})
    await audit_log(
        action="LOAN_UPDATED",
        request=request,
        user={"user_id": user_id},
        meta={"account_id": account_id, **{k: v for k, v in updates.items() if k != "updated_at" and k != "next_due_date"}},
    )


async def pay_loan_emi(*, user_id: str, account_id: str, request: Request | None = None) -> dict:
    account = await db.accounts.find_one(
        {"_id": ObjectId(account_id), "user_id": ObjectId(user_id), "deleted_at": None}
    )
    if not account or account.get("type") != "loan":
        raise NotFoundError("Loan not found")
    result = await apply_loan_cycle(user_id=user_id, account=account, request=request, force=True)
    if not result:
        raise ValidationError("No EMI left to apply on this loan")
    return result
