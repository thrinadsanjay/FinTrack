from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from app.web.templates import templates
from app.services.accounts import get_accounts, create_account, update_account, delete_account

router = APIRouter()

ACCOUNT_TYPES = [
    ("savings", "Savings"),
    ("current", "Current"),
    ("credit_card", "Credit Card"),
    ("wallet", "Wallet"),
    ("cash", "Cash"),
    ("investment", "Investment"),
    ("other", "Other"),
]

def require_user(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user


@router.get("")
async def accounts_page(request: Request):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user
    accounts = await get_accounts(user["user_id"])    
    return templates.TemplateResponse(
        "accounts.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "account_types": ACCOUNT_TYPES,
            "active_page": "accounts",
        },
    )



@router.post("/add")
async def add_account(
    request: Request,
    bank_name: str = Form(...),
    acc_type: str = Form(...),
    opening_balance: float = Form(...),
    name: str | None = Form(None),
):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    try:
        await create_account(
        user_id=user["user_id"],
        name=name,
        bank_name=bank_name,
        acc_type=acc_type,
        opening_balance=opening_balance,
    )
    except HTTPException as e:
        return templates.TemplateResponse(
            "accounts.html",
            {
                "request": request,
                "error": e.detail,
                "accounts": await get_accounts(user["user_id"]),
                "account_types": ACCOUNT_TYPES,
            },
            status_code=400,
        )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/edit")
async def edit_account(
    request: Request,
    account_id: str = Form(...),
    bank_name: str = Form(...),
    acc_type: str = Form(...),
    name: str = Form(...),
):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    await update_account(
        user_id=user["user_id"],
        account_id=account_id,
        name=name,
        bank_name=bank_name,
        acc_type=acc_type,
    )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/delete")
async def remove_account(
    request: Request,
    account_id: str = Form(...),
):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    await delete_account(
        user_id=user["user_id"],
        account_id=account_id,
    )

    return RedirectResponse("/accounts", status_code=303)
