"""JSON API for credit card management."""

from fastapi import APIRouter, Depends, Request, status

from app.routers.deps import get_current_user
from app.schemas.credit_cards import (
    CreditBillPaymentCreate,
    CreditBillUpdate,
    CreditCardCreate,
    CreditCardTransactionCreate,
    CreditCardTransactionUpdate,
    CreditCardUpdate,
    CreditEmiCreate,
    CreditEmiUpdate,
)
from app.services.credit_cards import (
    add_credit_card_transaction,
    calculate_card_utilization,
    calculate_estimated_bill,
    create_credit_card,
    create_emi_plan,
    delete_credit_card,
    delete_emi_plan,
    generate_bill_snapshot,
    get_bill,
    get_credit_card,
    get_credit_card_transaction,
    get_emi_schedule,
    get_liability_forecast,
    get_multi_card_summary,
    list_bills,
    list_credit_card_transactions,
    list_credit_cards,
    list_emi_plans,
    delete_credit_card_transaction,
    list_payments,
    record_bill_payment,
    update_bill,
    update_credit_card,
    update_credit_card_transaction,
    update_emi_plan,
)

router = APIRouter()


def _user_id(user: dict) -> str:
    return str(user.get("user_id") or user.get("_id") or "")


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_credit_card_endpoint(payload: CreditCardCreate, request: Request, user=Depends(get_current_user)):
    return await create_credit_card(user_id=_user_id(user), payload=payload, request=request)


@router.get("/")
async def list_credit_cards_endpoint(user=Depends(get_current_user)):
    return await list_credit_cards(user_id=_user_id(user))


@router.get("/summary")
async def credit_card_summary_endpoint(user=Depends(get_current_user)):
    return await get_multi_card_summary(user_id=_user_id(user))


@router.get("/liability-forecast")
async def liability_forecast_endpoint(months: int = 3, user=Depends(get_current_user)):
    return await get_liability_forecast(user_id=_user_id(user), months=months)


@router.get("/{card_id}")
async def get_credit_card_endpoint(card_id: str, user=Depends(get_current_user)):
    return await get_credit_card(user_id=_user_id(user), card_id=card_id)


@router.patch("/{card_id}")
async def update_credit_card_endpoint(card_id: str, payload: CreditCardUpdate, request: Request, user=Depends(get_current_user)):
    return await update_credit_card(user_id=_user_id(user), card_id=card_id, payload=payload, request=request)


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credit_card_endpoint(card_id: str, request: Request, user=Depends(get_current_user)):
    await delete_credit_card(user_id=_user_id(user), card_id=card_id, request=request)


@router.post("/{card_id}/transactions", status_code=status.HTTP_201_CREATED)
async def add_credit_card_transaction_endpoint(card_id: str, payload: CreditCardTransactionCreate, request: Request, user=Depends(get_current_user)):
    return await add_credit_card_transaction(user_id=_user_id(user), card_id=card_id, payload=payload, request=request)


@router.get("/{card_id}/transactions")
async def list_credit_card_transactions_endpoint(card_id: str, limit: int = 200, user=Depends(get_current_user)):
    return await list_credit_card_transactions(user_id=_user_id(user), card_id=card_id, limit=limit)


@router.get("/{card_id}/transactions/{txn_id}")
async def get_credit_card_transaction_endpoint(card_id: str, txn_id: str, user=Depends(get_current_user)):
    return await get_credit_card_transaction(user_id=_user_id(user), card_id=card_id, txn_id=txn_id)


@router.patch("/{card_id}/transactions/{txn_id}")
async def update_credit_card_transaction_endpoint(card_id: str, txn_id: str, payload: CreditCardTransactionUpdate, request: Request, user=Depends(get_current_user)):
    return await update_credit_card_transaction(user_id=_user_id(user), card_id=card_id, txn_id=txn_id, payload=payload, request=request)


@router.delete("/{card_id}/transactions/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credit_card_transaction_endpoint(card_id: str, txn_id: str, request: Request, user=Depends(get_current_user)):
    await delete_credit_card_transaction(user_id=_user_id(user), card_id=card_id, txn_id=txn_id, request=request)


@router.get("/{card_id}/estimated-bill")
async def estimated_bill_endpoint(card_id: str, user=Depends(get_current_user)):
    return await calculate_estimated_bill(user_id=_user_id(user), card_id=card_id)


@router.post("/{card_id}/bills/generate", status_code=status.HTTP_201_CREATED)
async def generate_bill_endpoint(card_id: str, request: Request, user=Depends(get_current_user)):
    return await generate_bill_snapshot(user_id=_user_id(user), card_id=card_id, request=request)


@router.get("/{card_id}/bills")
async def list_bills_endpoint(card_id: str, user=Depends(get_current_user)):
    return await list_bills(user_id=_user_id(user), card_id=card_id)


@router.get("/{card_id}/bills/{bill_id}")
async def get_bill_endpoint(card_id: str, bill_id: str, user=Depends(get_current_user)):
    return await get_bill(user_id=_user_id(user), card_id=card_id, bill_id=bill_id)


@router.patch("/{card_id}/bills/{bill_id}")
async def update_bill_endpoint(card_id: str, bill_id: str, payload: CreditBillUpdate, request: Request, user=Depends(get_current_user)):
    return await update_bill(user_id=_user_id(user), card_id=card_id, bill_id=bill_id, payload=payload, request=request)


@router.post("/{card_id}/bills/{bill_id}/adjustment")
async def adjust_bill_endpoint(card_id: str, bill_id: str, payload: CreditBillUpdate, request: Request, user=Depends(get_current_user)):
    return await update_bill(user_id=_user_id(user), card_id=card_id, bill_id=bill_id, payload=payload, request=request)


@router.post("/{card_id}/bills/{bill_id}/mark-paid")
async def mark_bill_paid_endpoint(card_id: str, bill_id: str, payload: CreditBillPaymentCreate, request: Request, user=Depends(get_current_user)):
    return await record_bill_payment(user_id=_user_id(user), card_id=card_id, bill_id=bill_id, payload=payload, request=request)


@router.post("/{card_id}/payments", status_code=status.HTTP_201_CREATED)
async def create_payment_endpoint(card_id: str, payload: CreditBillPaymentCreate, request: Request, user=Depends(get_current_user)):
    bill = await generate_bill_snapshot(user_id=_user_id(user), card_id=card_id, request=request)
    return await record_bill_payment(user_id=_user_id(user), card_id=card_id, bill_id=bill["id"], payload=payload, request=request)


@router.get("/{card_id}/payments")
async def list_payments_endpoint(card_id: str, user=Depends(get_current_user)):
    return await list_payments(user_id=_user_id(user), card_id=card_id)


@router.get("/{card_id}/utilization")
async def card_utilization_endpoint(card_id: str, user=Depends(get_current_user)):
    return await calculate_card_utilization(user_id=_user_id(user), card_id=card_id)


@router.post("/{card_id}/emis", status_code=status.HTTP_201_CREATED)
async def create_emi_endpoint(card_id: str, payload: CreditEmiCreate, request: Request, user=Depends(get_current_user)):
    return await create_emi_plan(user_id=_user_id(user), card_id=card_id, payload=payload, request=request)


@router.get("/{card_id}/emis")
async def list_emis_endpoint(card_id: str, user=Depends(get_current_user)):
    return await list_emi_plans(user_id=_user_id(user), card_id=card_id)


@router.patch("/{card_id}/emis/{emi_id}")
async def update_emi_endpoint(card_id: str, emi_id: str, payload: CreditEmiUpdate, request: Request, user=Depends(get_current_user)):
    return await update_emi_plan(user_id=_user_id(user), card_id=card_id, emi_id=emi_id, payload=payload, request=request)


@router.delete("/{card_id}/emis/{emi_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_emi_endpoint(card_id: str, emi_id: str, request: Request, user=Depends(get_current_user)):
    await delete_emi_plan(user_id=_user_id(user), card_id=card_id, emi_id=emi_id, request=request)


@router.get("/{card_id}/emis/{emi_id}/schedule")
async def emi_schedule_endpoint(card_id: str, emi_id: str, user=Depends(get_current_user)):
    return await get_emi_schedule(user_id=_user_id(user), card_id=card_id, emi_id=emi_id)
