from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from app.core.csrf import verify_csrf_token
from app.core.errors import AppError
from app.web.templates import templates
from app.core.guards import login_required
from app.services.accounts import (
    get_accounts,
    create_account,
    update_account_name,
    update_account_balance,
    delete_account,
)
from app.services.dashboard import get_user_notifications


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
# LIST ACCOUNTS
# ======================================================

@router.get("")
@login_required
async def accounts_page(request: Request):
    user = request.session.get("user")
    accounts = await get_accounts(user["user_id"])
    notifications = await get_user_notifications(user["user_id"])

    return templates.TemplateResponse(
        "accounts.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "account_types": ACCOUNT_TYPES,
            "notifications": notifications,
            "active_page": "accounts",
        },
    )


# ======================================================
# ADD ACCOUNT
# ======================================================

@router.post("/add")
@login_required
async def add_account(
    request: Request,
    bank_name: str = Form(...),
    acc_type: str = Form(...),
    balance: float = Form(...),
    name: str | None = Form(None),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await create_account(
            user_id=user["user_id"],
            name=name,
            bank_name=bank_name,
            acc_type=acc_type,
            balance=balance,
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            "accounts.html",
            {
                "request": request,
                "user": user,
                "error": str(e),
                "accounts": await get_accounts(user["user_id"]),
                "account_types": ACCOUNT_TYPES,
                "notifications": await get_user_notifications(user["user_id"]),
                "active_page": "accounts",
            },
            status_code=e.status_code,
        )

    return RedirectResponse("/accounts", status_code=303)


# ======================================================
# RENAME ACCOUNT (NAME ONLY)
# ======================================================

@router.post("/rename")
@login_required
async def rename_account(
    request: Request,
    account_id: str = Form(...),
    name: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    await update_account_name(
        user_id=user["user_id"],
        account_id=account_id,
        name=name,
        request=request,
    )

    return RedirectResponse("/accounts", status_code=303)


# ======================================================
# EDIT ACCOUNT (BALANCE ONLY)
# ======================================================

@router.post("/edit")
@login_required
async def edit_account(
    request: Request,
    account_id: str = Form(...),
    balance: float = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    await update_account_balance(
        user_id=user["user_id"],
        account_id=account_id,
        balance=balance,
        request=request,
    )

    return RedirectResponse("/accounts", status_code=303)

# ======================================================
# DELETE ACCOUNT (SOFT DELETE)
# ======================================================

@router.post("/delete")
@login_required
async def remove_account(
    request: Request,
    account_id: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await delete_account(
            user_id=user["user_id"],
            account_id=account_id,
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            "accounts.html",
            {
                "request": request,
                "user": user,
                "error": str(e),
                "accounts": await get_accounts(user["user_id"]),
                "account_types": ACCOUNT_TYPES,
                "notifications": await get_user_notifications(user["user_id"]),
                "active_page": "accounts",
            },
            status_code=e.status_code,
        )

    return RedirectResponse("/accounts", status_code=303)
