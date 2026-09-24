"""
Convert a credit-card spend into an EMI plan.

Responsibilities:
- Validate the spend (debit on a credit-card account, not already converted)
- Create the EMI plan and its ledger entries (processing fee, projected interest)
- Keep the fee debit and its ledger row atomic

This module MUST NOT:
- Render templates
- Redirect responses
- Access session directly
"""

from datetime import date, datetime, timedelta, timezone

from bson import ObjectId

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.mongo import db, run_atomic
from app.helpers.account_balances import apply_account_delta
from app.helpers.loan_math import emi_conversion_details
from app.services.accounts import add_credit_card_emi

SYSTEM_EMI_SOURCES = {"emi_processing_fee", "emi_interest_projection"}


async def _insert_emi_ledger_entries(
    *,
    user_oid: ObjectId,
    account_oid: ObjectId,
    category: dict,
    subcategory: dict,
    title: str,
    processing_fee_amount: float,
    estimated_interest: float,
    source_transaction_id: str,
) -> None:
    now = datetime.now(timezone.utc)
    base = {
        "user_id": user_oid,
        "account_id": account_oid,
        "type": "debit",
        "mode": "online",
        "category": category,
        "subcategory": subcategory,
        "created_at": now,
        "deleted_at": None,
    }

    if processing_fee_amount > 0:
        fee = round(processing_fee_amount, 2)
        fee_doc = {
            **base,
            "amount": fee,
            "description": f"EMI processing fee: {title}",
            "source": "emi_processing_fee",
            "meta": {
                "source_transaction_id": source_transaction_id,
                "ledger_kind": "emi_processing_fee",
            },
        }

        async def _write_fee(session):
            await db.transactions.insert_one(dict(fee_doc), session=session)
            await apply_account_delta(db=db, account_id=account_oid, delta=-fee, session=session)

        await run_atomic(_write_fee)

    if estimated_interest > 0:
        await db.transactions.insert_one(
            {
                **base,
                "amount": round(estimated_interest, 2),
                "description": f"EMI projected interest: {title}",
                "source": "emi_interest_projection",
                "excluded_from_balance": True,
                "meta": {
                    "source_transaction_id": source_transaction_id,
                    "ledger_kind": "emi_projected_interest",
                },
            }
        )


async def convert_transaction_to_emi(
    *,
    user_id: str,
    transaction_id: str,
    tenure_months: int,
    interest_rate: float = 0.0,
    processing_fee_rate: float = 0.0,
    title: str | None = None,
    request=None,
) -> dict[str, float]:
    if tenure_months <= 1:
        raise ValidationError("EMI tenure must be at least 2 months")
    if interest_rate < 0 or processing_fee_rate < 0:
        raise ValidationError("ROI and processing fee cannot be negative")

    user_oid = ObjectId(user_id)
    tx_oid = ObjectId(transaction_id)
    tx = await db.transactions.find_one({"_id": tx_oid, "user_id": user_oid, "deleted_at": None})
    if not tx:
        raise NotFoundError("Transaction not found")
    if str(tx.get("type") or "") != "debit":
        raise ValidationError("Only debit transactions can be converted to EMI")
    if tx.get("source") in SYSTEM_EMI_SOURCES:
        raise ValidationError("System generated EMI entries cannot be converted")

    account_oid = tx.get("account_id")
    account_doc = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None},
        {"type": 1},
    )
    if not account_doc or str(account_doc.get("type") or "") != "credit_card":
        raise ValidationError("EMI conversion is available only for credit card spends")

    amount = float(tx.get("amount") or 0)
    if amount <= 0:
        raise ValidationError("Only positive transactions can be converted")

    values = emi_conversion_details(
        amount=amount,
        tenure=int(tenure_months),
        roi=float(interest_rate),
        processing_rate=float(processing_fee_rate),
    )
    emi_title = (title or tx.get("description") or "Converted EMI").strip() or "Converted EMI"

    # Claim the spend first so a double submit cannot create two plans / two fees.
    claimed = await db.transactions.update_one(
        {"_id": tx_oid, "emi_conversion.converted": {"$ne": True}},
        {
            "$set": {
                "emi_conversion": {
                    "converted": True,
                    "converted_at": datetime.now(timezone.utc),
                    "tenure_months": int(tenure_months),
                    "interest_rate": float(interest_rate),
                    "processing_fee_rate": float(processing_fee_rate),
                    "processing_fee_amount": values["processing_fee_amount"],
                    "estimated_interest": values["estimated_interest"],
                }
            }
        },
    )
    if claimed.modified_count == 0:
        raise ConflictError("This transaction is already converted to EMI")

    try:
        await add_credit_card_emi(
            user_id=user_id,
            account_id=str(account_oid),
            title=emi_title,
            total_amount=values["financed_amount"],
            monthly_amount=values["monthly_amount"],
            total_installments=int(tenure_months),
            remaining_installments=int(tenure_months),
            interest_rate=float(interest_rate),
            next_due_date=date.today() + timedelta(days=30),
            request=request,
        )
    except Exception:
        await db.transactions.update_one({"_id": tx_oid}, {"$unset": {"emi_conversion": ""}})
        raise

    await _insert_emi_ledger_entries(
        user_oid=user_oid,
        account_oid=account_oid,
        category=tx.get("category") or {"code": "other", "name": "Other"},
        subcategory=tx.get("subcategory") or {"code": "other", "name": "Other"},
        title=emi_title,
        processing_fee_amount=values["processing_fee_amount"],
        estimated_interest=values["estimated_interest"],
        source_transaction_id=transaction_id,
    )
    return values
