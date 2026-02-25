"""
JSON API for transactions.
No templates. No audit calls.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.routers.deps import get_current_user
from app.services.transactions import create_transaction

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def add_transaction(
    request: Request,
    account_id: str,
    amount: int,
    tx_type: str,
    mode: str,
    category_code: str,
    subcategory_code: str,
    description: str = "",
    user=Depends(get_current_user),
):
    user_id = user.get("user_id") or user.get("_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session user")

    tx_id = await create_transaction(
        user_id=user_id,
        account_id=account_id,
        amount=amount,
        tx_type=tx_type,
        mode=mode,
        category_code=category_code,
        subcategory_code=subcategory_code,
        description=description,
        request=request,
    )

    return {
        "id": str(tx_id),
        "account_id": account_id,
        "type": tx_type,
        "amount": amount,
    }
