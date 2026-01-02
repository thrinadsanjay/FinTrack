from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from app.web.templates import templates
from app.services.accounts import (
    get_accounts,
    create_account,
    update_account_name,
    delete_account,
)

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


# ======================================================
# AUTH GUARD
# ======================================================

def require_user(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)
    return user


# ======================================================
# LIST ACCOUNTS
# ======================================================

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


# ======================================================
# ADD ACCOUNT
# ======================================================

@router.post("/add")
async def add_account(
    request: Request,
    bank_name: str = Form(...),
    acc_type: str = Form(...),
    balance: float = Form(...),
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
            balance=balance,
            request=request,
        )
    except Exception as e:
        return templates.TemplateResponse(
            "accounts.html",
            {
                "request": request,
                "error": str(e),
                "accounts": await get_accounts(user["user_id"]),
                "account_types": ACCOUNT_TYPES,
            },
            status_code=400,
        )

    return RedirectResponse("/accounts", status_code=303)


# ======================================================
# RENAME ACCOUNT (NAME ONLY)
# ======================================================

@router.post("/rename")
async def rename_account(
    request: Request,
    account_id: str = Form(...),
    name: str = Form(...),
):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    await update_account_name(
        user_id=user["user_id"],
        account_id=account_id,
        name=name,
        request=request,
    )

    return RedirectResponse("/accounts", status_code=303)


# ======================================================
# DELETE ACCOUNT (SOFT DELETE)
# ======================================================

@router.post("/delete")
async def remove_account(
    request: Request,
    account_id: str = Form(...),
):
    user = require_user(request)
    if isinstance(user, RedirectResponse):
        return user

    try:
        await delete_account(
            user_id=user["user_id"],
            account_id=account_id,
            request=request,
        )
    except Exception as e:
        return templates.TemplateResponse(
            "accounts.html",
            {
                "request": request,
                "error": str(e),
                "accounts": await get_accounts(user["user_id"]),
                "account_types": ACCOUNT_TYPES,
            },
            status_code=400,
        )

    return RedirectResponse("/accounts", status_code=303)
