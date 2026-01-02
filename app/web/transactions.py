from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse

from app.web.templates import templates
from app.services.accounts import get_accounts
from app.services.transactions import (
    create_transaction,
    get_user_transactions,
    delete_transaction,
    restore_transaction,
    edit_transaction,
)
from app.core.guards import (
    is_within_edit_window,
    can_restore_today,
)

router = APIRouter()

EDIT_WINDOW_DAYS = 2
RESTORE_WINDOW_HOURS = 24


# ======================================================
# ADD TRANSACTION PAGE
# ======================================================

@router.get("", response_class=HTMLResponse)
async def transactions_page(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    accounts = await get_accounts(user["user_id"])

    return templates.TemplateResponse(
        "transactions_add.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "active_page": "addtransaction",
        },
    )


# ======================================================
# CREATE TRANSACTION
# ======================================================

@router.post("/add")
async def add_transaction(
    request: Request,
    account_id: str = Form(...),
    tx_type: str = Form(...),
    category_code: str = Form(...),
    subcategory_code: str = Form(...),
    amount: float = Form(...),
    description: str = Form(""),
    target_account_id: str | None = Form(None),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    await create_transaction(
        user_id=user["user_id"],
        account_id=account_id,
        target_account_id=target_account_id,
        amount=amount,
        tx_type=tx_type,
        category_code=category_code,
        subcategory_code=subcategory_code,
        description=description,
        request=request,
    )

    return RedirectResponse("/transactions", status_code=303)


# ======================================================
# LIST TRANSACTIONS
# ======================================================

@router.get("/list", response_class=HTMLResponse)
async def transactions_list_page(
    request: Request,
    account_id: str | None = Query(None),
    tx_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    category_code: str | None = Query(None),
    subcategory_code: str | None = Query(None),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    transactions = await get_user_transactions(
        user_id=user["user_id"],
        account_id=account_id,
        tx_type=tx_type,
        date_from=date_from,
        date_to=date_to,
        category_code=category_code,
        subcategory_code=subcategory_code,
    )

    accounts = await get_accounts(user["user_id"])
    account_map = {str(acc["_id"]): acc["name"] for acc in accounts}

    now = datetime.now(timezone.utc)

    # --------------------------------------------------
    # PRE-COMPUTE UI FLAGS (NO JINJA LOGIC)
    # --------------------------------------------------
    for tx in transactions:
        created_at = tx.get("created_at")

        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
            tx["created_at"] = created_at

        tx["is_deleted"] = tx.get("deleted_at") is not None
        tx["can_modify"] = (
            not tx["is_deleted"]
            and created_at
            and is_within_edit_window(created_at)
        )

        tx["can_restore"] = (
            tx["is_deleted"]
            and can_restore_today(tx["deleted_at"])
        )

        tx["lock_time"] = (
            created_at + timedelta(days=EDIT_WINDOW_DAYS)
            if created_at else None
        )

        # Placeholder for future month-close feature
        tx["is_month_closed"] = False

    return templates.TemplateResponse(
        "transactions_list.html",
        {
            "request": request,
            "user": user,
            "transactions": transactions,
            "accounts": accounts,
            "account_map": account_map,
            "filters": {
                "account_id": account_id,
                "tx_type": tx_type,
                "date_from": date_from,
                "date_to": date_to,
                "category_code": category_code,
                "subcategory_code": subcategory_code,
            },
            "active_page": "listtransactions",
        },
    )


# ======================================================
# DELETE TRANSACTION
# ======================================================

@router.post("/delete")
async def delete_transaction_route(
    request: Request,
    transaction_id: str = Form(...),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    await delete_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        request=request,
    )

    return RedirectResponse("/transactions/list", status_code=303)


# ======================================================
# RESTORE TRANSACTION
# ======================================================

@router.post("/restore")
async def restore_transaction_route(
    request: Request,
    transaction_id: str = Form(...),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    await restore_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        request=request,
    )

    return RedirectResponse("/transactions/list", status_code=303)



# ======================================================
# EDIT TRANSACTION
# ======================================================

@router.post("/edit")
async def edit_transaction_submit(
    request: Request,
    transaction_id: str = Form(...),
    account_id: str = Form(...),
    amount: float = Form(...),
    category_code: str = Form(...),
    subcategory_code: str = Form(...),
    description: str = Form(""),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    await edit_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        new_account_id=account_id,
        new_amount=amount,
        new_category_code=category_code,
        new_subcategory_code=subcategory_code,
        new_description=description,
        request=request,
    )

    return RedirectResponse("/transactions/list", status_code=303)
