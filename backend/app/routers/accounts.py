from fastapi import APIRouter, Depends, Request, status
from app.services.auth import get_current_user
from app.services.accounts import create_account
from app.services.audit import create_audit_log

router = APIRouter()

@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_account_endpoint(
    request: Request,
    name: str,
    currency: str = "INR",
    user=Depends(get_current_user),
):
    account = await create_account(
        user_id=user["_id"],
        name=name,
        currency=currency,
    )

    await create_audit_log(
        user=user,
        action="create_account",
        resource=str(account["_id"]),
        request=request,
    )

    return {
        "id": str(account["_id"]),
        "name": account["name"],
        "currency": account["currency"],
        "balance": account["balance"],
    }
