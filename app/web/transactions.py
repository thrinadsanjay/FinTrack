"""
UI controller for transactions.
Handles forms, templates, redirects.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from app.core.csrf import verify_csrf_token
from app.core.errors import AppError, ValidationError
from app.web.templates import templates
from app.services.recurring_deposit import RecurringDepositService
from app.services.accounts import get_accounts
from app.services.dashboard import get_user_notifications
from app.services.transactions import (
    create_transaction,
    get_user_transactions,
    delete_transaction,
    restore_transaction,
    edit_transaction,
    retry_failed_recurring_transaction,
)
from app.core.guards import is_within_edit_window, can_restore_today, is_month_closed, login_required

router = APIRouter()

EDIT_WINDOW_DAYS = 2
is_recurring = None


@router.get("", response_class=HTMLResponse)
async def transactions_page(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    accounts = await get_accounts(user["user_id"])
    notifications = await get_user_notifications(user["user_id"])

    return templates.TemplateResponse(
        "transactions_add.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "notifications": notifications,
            "active_page": "addtransaction",
        },
    )


@router.post("/add")
@login_required
async def add_transaction(
    request: Request,
    account_id: str = Form(...),
    tx_type: str = Form(...),
    mode: str = Form(...),
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
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")

    if is_recurring:
        if not frequency:
            raise ValidationError("Recurring frequency is required")

    if tx_type == "transfer" and not target_account_id:
        raise ValidationError("Target account is required for transfers")

    try:
        await create_transaction(
            user_id=user["user_id"],
            account_id=account_id,
            target_account_id=target_account_id,
            amount=amount,
            tx_type=tx_type,
            mode=mode,
            category_code=category_code,
            subcategory_code=subcategory_code,
            description=description,
            is_recurring=is_recurring,
            frequency=frequency,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            request=request,
        )
    except AppError as exc:
        accounts = await get_accounts(user["user_id"])
        notifications = await get_user_notifications(user["user_id"])
        return templates.TemplateResponse(
            "transactions_add.html",
            {
                "request": request,
                "user": user,
                "accounts": accounts,
                "notifications": notifications,
                "active_page": "addtransaction",
                "error": exc.detail,
            },
            status_code=exc.status_code,
        )
    except Exception:
        accounts = await get_accounts(user["user_id"])
        notifications = await get_user_notifications(user["user_id"])
        return templates.TemplateResponse(
            "transactions_add.html",
            {
                "request": request,
                "user": user,
                "accounts": accounts,
                "notifications": notifications,
                "active_page": "addtransaction",
                "error": "Unable to add transaction right now. Please retry.",
            },
            status_code=500,
        )

    return RedirectResponse("/transactions", status_code=303)

# ======================================================
# LIST TRANSACTIONS
# ======================================================

@router.get("/list", response_class=HTMLResponse)
@login_required
async def transactions_list_page(
    request: Request,
    account_id: str | None = Query(None),
    tx_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    category_code: str | None = Query(None),
    subcategory_code: str | None = Query(None),
    search: str | None = Query(None),
    amount: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_dir: str | None = Query(None),
):
    user = request.session.get("user")

    amount_value: float | None = None
    if amount is not None and amount.strip() != "":
        try:
            amount_value = float(amount)
        except ValueError:
            amount_value = None

    transactions = await get_user_transactions(
        user_id=user["user_id"],
        account_id=account_id,
        tx_type=tx_type,
        date_from=date_from,
        date_to=date_to,
        category_code=category_code,
        subcategory_code=subcategory_code,
        search=search,
        amount=amount_value,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    accounts = await get_accounts(user["user_id"])
    notifications = await get_user_notifications(user["user_id"])
    account_map = {str(acc["_id"]): acc["name"] for acc in accounts}

    # --------------------------------------------------
    # MERGE SELF TRANSFERS INTO SINGLE ROW
    # --------------------------------------------------
    transfer_groups = {}
    merged = []
    for tx in transactions:
        transfer_id = tx.get("transfer_id")
        if not transfer_id:
            merged.append(tx)
            continue
        transfer_groups.setdefault(str(transfer_id), []).append(tx)

    for items in transfer_groups.values():
        source = next((t for t in items if t.get("type") == "transfer_out"), None)
        target = next((t for t in items if t.get("type") == "transfer_in"), None)
        base = source or target or items[0]
        merged.append(
            {
                "_id": base.get("_id"),
                "transfer_id": base.get("transfer_id"),
                "type": "transfer",
                "amount": base.get("amount", 0),
                "description": base.get("description", "Transfer"),
                "created_at": base.get("created_at"),
                "deleted_at": base.get("deleted_at"),
                "category": None,
                "subcategory": None,
                "from_account": (source or base).get("account_id"),
                "to_account": (target or base).get("account_id") or base.get("target_account_id"),
                "source": base.get("source"),
                "is_failed": bool(base.get("is_failed")),
                "failure_reason": base.get("failure_reason"),
                "retry_status": base.get("retry_status", "pending"),
            }
        )

    transactions = merged

    # --------------------------------------------------
    # SORT AFTER MERGE (TRANSFER ROWS)
    # --------------------------------------------------
    if sort_by:
        reverse = (sort_dir or "desc").lower() == "desc"

        def sort_key(tx):
            if sort_by == "date":
                return tx.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)
            if sort_by == "amount":
                return tx.get("amount") or 0
            if sort_by == "account":
                account_id = str(tx.get("account_id") or tx.get("from_account") or "")
                return account_map.get(account_id, "")
            if sort_by == "category":
                cat = tx.get("category") or {}
                return cat.get("name", "")
            if sort_by == "subcategory":
                sub = tx.get("subcategory") or {}
                return sub.get("name", "")
            return tx.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)

        transactions = sorted(transactions, key=sort_key, reverse=reverse)

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
        tx["is_failed"] = bool(tx.get("is_failed"))
        tx["retry_status"] = tx.get("retry_status", "pending")
        tx["can_retry"] = (
            tx["is_failed"]
            and tx.get("failure_reason") == "insufficient_funds"
            and tx["retry_status"] != "resolved"
        )

        tx["can_modify"] = (
            not tx["is_deleted"]
            and created_at
            and is_within_edit_window(created_at)
        )
        if tx["is_failed"]:
            tx["can_modify"] = False

        tx["can_restore"] = (
            tx["is_deleted"]
            and can_restore_today(tx["deleted_at"])
        )
        if tx["is_failed"]:
            tx["can_restore"] = False

        tx["lock_time"] = (
            created_at + timedelta(days=EDIT_WINDOW_DAYS)
            if created_at else None
        )

        tx["is_month_closed"] = False  # future feature

    def _sort_link(field: str):
        current_dir = (sort_dir or "desc").lower()
        next_dir = "asc" if (sort_by == field and current_dir == "desc") else "desc"
        return str(request.url.include_query_params(sort_by=field, sort_dir=next_dir))

    return templates.TemplateResponse(
        "transactions_list.html",
        {
            "request": request,
            "user": user,
            "transactions": transactions,
            "accounts": accounts,
            "account_map": account_map,
            "notifications": notifications,
            "filters": {
                "account_id": account_id,
                "tx_type": tx_type,
                "date_from": date_from,
                "date_to": date_to,
                "category_code": category_code,
                "subcategory_code": subcategory_code,
                "search": search,
                "amount": amount or "",
            },
            "active_filter_count": sum(
                1 for v in [account_id, tx_type, date_from, date_to, category_code, subcategory_code, search, amount]
                if v
            ),
            "sort_by": sort_by or "date",
            "sort_dir": (sort_dir or "desc").lower(),
            "sort_links": {
                "date": _sort_link("date"),
                "amount": _sort_link("amount"),
                "account": _sort_link("account"),
                "category": _sort_link("category"),
                "subcategory": _sort_link("subcategory"),
            },
            "active_page": "listtransactions",
        },
    )

@router.post("/delete")
@login_required
async def delete_transaction_ui(
    request: Request,
    transaction_id: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    await delete_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        request=request,
    )

    return RedirectResponse("/transactions/list", status_code=303)

@router.post("/restore")
@login_required
async def restore_transaction_ui(
    request: Request,
    transaction_id: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    await restore_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        request=request,
    )

    return RedirectResponse("/transactions/list", status_code=303)

@router.post("/edit")
@login_required
async def edit_transaction_ui(
    request: Request,
    transaction_id: str = Form(...),
    account_id: str = Form(...),
    amount: float = Form(...),
    category_code: str = Form(...),
    subcategory_code: str = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
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


@router.post("/retry-failed")
@login_required
async def retry_failed_transaction_ui(
    request: Request,
    transaction_id: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    await retry_failed_recurring_transaction(
        user_id=user["user_id"],
        failed_transaction_id=transaction_id,
        request=request,
    )
    return RedirectResponse("/transactions/list", status_code=303)

@router.get("", response_class=HTMLResponse)
@login_required
async def transactions_default(request: Request):
    return await transactions_list_page(request)
