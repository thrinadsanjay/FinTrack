"""
JSON API for accounts.
No templates, no audit calls.
"""

from fastapi import APIRouter, Depends, Request, status
from app.routers.deps import get_current_user
from app.services.accounts import create_account

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_account_endpoint(
    request: Request,
    bank_name: str,
    acc_type: str,
    balance: float,
    name: str | None = None,
    user=Depends(get_current_user),
):
    account_id = await create_account(
        user_id=user["_id"],
        name=name,
        bank_name=bank_name,
        acc_type=acc_type,
        balance=balance,
        request=request,
    )

    return {
        "id": str(account_id),
        "name": name or bank_name,
        "bank_name": bank_name,
        "type": acc_type,
        "balance": balance,
    }
