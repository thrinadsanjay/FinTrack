"""
UI controller for transactions.
Handles forms, templates, redirects.
"""

from datetime import datetime, timedelta, timezone
<<<<<<< HEAD
from typing import Optional
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from app.web.templates import templates
from app.services.recurring_deposit import RecurringDepositService
=======
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse

from app.web.templates import templates
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
from app.services.accounts import get_accounts
from app.services.transactions import (
    create_transaction,
    get_user_transactions,
    delete_transaction,
    restore_transaction,
    edit_transaction,
)
from app.core.guards import is_within_edit_window, can_restore_today

router = APIRouter()

EDIT_WINDOW_DAYS = 2
<<<<<<< HEAD
is_recurring = None
=======
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271


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
    is_recurring: bool = Form(False),
    frequency: str | None = Form(None),
    interval: int = Form(1),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

<<<<<<< HEAD
    if is_recurring:
        if not frequency:
            raise Exception("Recurring frequency is required")

    if type == "transfer" and not target_account_id:
        raise Exception("Target account is required for transfers")
=======
    recurring = None
    if is_recurring:
        recurring = {
            "frequency": frequency,
            "interval": interval,
            "start_date": (
                datetime.fromisoformat(start_date).date()
                if start_date else None
            ),
            "end_date": (
                datetime.fromisoformat(end_date).date()
                if end_date else None
            ),
        }
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271

    await create_transaction(
        user_id=user["user_id"],
        account_id=account_id,
        target_account_id=target_account_id,
        amount=amount,
        tx_type=tx_type,
        category_code=category_code,
        subcategory_code=subcategory_code,
        description=description,
<<<<<<< HEAD
        is_recurring=is_recurring,
        frequency=frequency,
        interval=interval,
        start_date=start_date,
        end_date=end_date,
=======
        recurring=recurring,
>>>>>>> 8266f8b43a3760f7716449025947c72b4e670271
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

    # --------------------------------------------------
    # UI FLAGS (NO JINJA LOGIC)
    # --------------------------------------------------
    now = datetime.now(timezone.utc)

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

        tx["is_month_closed"] = False  # future feature

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

@router.get("", response_class=HTMLResponse)
async def transactions_default(request: Request):
    return await transactions_list_page(request)
