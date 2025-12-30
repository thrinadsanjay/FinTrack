from fastapi import APIRouter, Depends, Request, status
from app.routers.deps import get_current_api_user
from app.services.transactions import create_transaction
from app.services.audit import audit_log

router = APIRouter()

@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_transaction(
    request: Request,
    account_id: str,
    amount: int,
    tx_type: str,  # debit | credit
    category: str | None = None,
    note: str | None = None,
    user=Depends(get_current_api_user),
):
    tx = await create_transaction(
        user_id=user["_id"],
        account_id=account_id,
        amount=amount,
        tx_type=tx_type,
        category=category,
        note=note,
    )

    await audit_log(
        user=user,
        action="create_transaction",
        resource=str(tx["_id"]),
        request=request,
    )

    return {
        "id": str(tx["_id"]),
        "account_id": account_id,
        "type": tx_type,
        "amount": amount,
        "balance_change": amount if tx_type == "credit" else -amount,
    }
