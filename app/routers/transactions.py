"""
JSON API for transactions.
No templates. No audit calls. All business rules live in app.services.transactions.
"""

from bson import ObjectId
from fastapi import APIRouter, Depends, Query, Request, status

from app.core.time import get_user_timezone
from app.routers.deps import get_current_user_valid as get_current_user
from app.schemas.transactions import (
    EmiConversionRequest,
    TransactionCreateRequest,
    TransactionEditRequest,
)
from app.services.emi_conversion import convert_transaction_to_emi
from app.services.transactions import (
    create_transaction,
    delete_transaction,
    edit_transaction,
    get_user_transactions,
    restore_transaction,
    retry_failed_recurring_transaction,
)

router = APIRouter()


def _jsonable(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {("id" if k == "_id" else k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


@router.get("/")
async def list_transactions(
    request: Request,
    account_id: str | None = None,
    tx_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category_code: str | None = None,
    subcategory_code: str | None = None,
    search: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    skip: int = Query(default=0, ge=0),
    user=Depends(get_current_user),
):
    rows = await get_user_transactions(
        user_id=user["user_id"],
        account_id=account_id,
        tx_type=tx_type,
        date_from=date_from,
        date_to=date_to,
        category_code=category_code,
        subcategory_code=subcategory_code,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        tz=get_user_timezone(request),
        limit=limit,
        skip=skip,
    )
    return {"items": [_jsonable(tx) for tx in rows], "limit": limit, "skip": skip}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_transaction(
    request: Request,
    payload: TransactionCreateRequest,
    user=Depends(get_current_user),
):
    tx_id = await create_transaction(
        user_id=user["user_id"],
        account_id=payload.account_id,
        amount=payload.amount,
        tx_type=payload.tx_type,
        mode=payload.mode,
        category_code=payload.category_code,
        subcategory_code=payload.subcategory_code,
        description=payload.description,
        target_account_id=payload.target_account_id,
        transfer_kind="card_payment" if payload.tx_type == "card_payment" else None,
        credit_bill_id=payload.credit_bill_id,
        is_recurring=payload.is_recurring,
        frequency=payload.frequency,
        interval=payload.interval,
        start_date=payload.start_date,
        end_date=payload.end_date,
        transaction_date=payload.transaction_date,
        request=request,
    )
    # None means a recurring rule was created with its first run in the future.
    return {"id": str(tx_id) if tx_id else None, "recurring_rule_only": tx_id is None}


@router.patch("/{transaction_id}")
async def update_transaction(
    request: Request,
    transaction_id: str,
    payload: TransactionEditRequest,
    user=Depends(get_current_user),
):
    await edit_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        new_account_id=payload.account_id,
        new_amount=payload.amount,
        new_category_code=payload.category_code,
        new_subcategory_code=payload.subcategory_code,
        new_description=payload.description,
        request=request,
    )
    return {"id": transaction_id}


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_transaction(request: Request, transaction_id: str, user=Depends(get_current_user)):
    await delete_transaction(user_id=user["user_id"], transaction_id=transaction_id, request=request)


@router.post("/{transaction_id}/restore")
async def restore(request: Request, transaction_id: str, user=Depends(get_current_user)):
    await restore_transaction(user_id=user["user_id"], transaction_id=transaction_id, request=request)
    return {"id": transaction_id}


@router.post("/{transaction_id}/retry")
async def retry(request: Request, transaction_id: str, user=Depends(get_current_user)):
    posted = await retry_failed_recurring_transaction(
        user_id=user["user_id"],
        failed_transaction_id=transaction_id,
        request=request,
    )
    return {"id": transaction_id, "posted": posted}


@router.post("/{transaction_id}/emi")
async def convert_to_emi(
    request: Request,
    transaction_id: str,
    payload: EmiConversionRequest,
    user=Depends(get_current_user),
):
    return await convert_transaction_to_emi(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        tenure_months=payload.tenure_months,
        interest_rate=payload.interest_rate,
        processing_fee_rate=payload.processing_fee_rate,
        title=payload.title,
        request=request,
    )
