"""
UI controller for transactions.
Handles forms, templates, redirects.
"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from app.core.csrf import verify_csrf_token
from app.core.errors import AppError, ValidationError
from app.web.templates import templates
from app.helpers.transaction_inputs import resolve_transfer_category_codes, validate_category
from app.services.categorization_engine import categorize_transaction, learn_from_override
from app.services.accounts import get_accounts
from app.services.categories import get_categories_by_type
from app.services.emi_conversion import convert_transaction_to_emi
from app.services.goal_links import goal_prompt_for_new_entry
from app.services.dashboard import get_user_notifications
from app.services.transactions import (
    create_transaction,
    get_user_transactions,
    delete_transaction,
    restore_transaction,
    edit_transaction,
    retry_failed_recurring_transaction,
)
from app.core.guards import login_required
from app.helpers.flash import flash_redirect
from app.helpers.goal_prompt import set_goal_prompt
from app.core.time import get_user_timezone, parse_user_date
from app.helpers.transaction_list_ui import (
    build_board_columns,
    enrich_transactions_for_ui,
    group_by_local_date,
    merge_transfer_rows,
    resolve_account_ids_for_search,
    transaction_kpis,
)
from app.services.users import get_tx_preferred_view, set_tx_preferred_view

router = APIRouter()
logger = logging.getLogger(__name__)

EDIT_WINDOW_DAYS = 2
is_recurring = None


def _normalize_tx_view(value: str | None) -> str | None:
    view = str(value or "").strip().lower()
    return view if view in {"list", "board"} else None


def _workspace_url(*, view: str | None = None, add: bool = False, extras: list[str] | None = None) -> str:
    if str(view or "").strip().lower() == "recurring":
        return "/recurring"
    params: list[str] = []
    chosen = _normalize_tx_view(view)
    if chosen:
        params.append(f"view={chosen}")
    if add:
        params.append("add=1")
    if extras:
        params.extend(extras)
    return "/transactions/list" + (("?" + "&".join(params)) if params else "")


def _is_recurring_return(value: str | None) -> bool:
    return str(value or "").strip().lower() == "recurring"


async def _add_error_page(request: Request, *, error: str, status_code: int, return_view: str | None):
    if _is_recurring_return(return_view):
        from app.web.recurring import _normalize_filters, _render_recurring_page

        return await _render_recurring_page(
            request=request,
            filters=_normalize_filters(),
            error=error,
            open_add=True,
            status_code=status_code,
        )
    return await _render_transactions_workspace(
        request,
        error=error,
        open_add=True,
        status_code=status_code,
        view_override=_normalize_tx_view(return_view),
    )


def _spendable_accounts(accounts: list) -> list:
    return [acc for acc in accounts if str(acc.get("type") or "") != "loan"]


def _add_query(request: Request) -> str:
    extras = []
    for key in ("view", "tx_type", "account_id", "target_account_id", "description", "mode", "amount", "credit_bill_id"):
        value = request.query_params.get(key)
        if value:
            extras.append(f"{key}={value}")
    suffix = ("&" + "&".join(extras)) if extras else ""
    return f"/transactions/list?add=1{suffix}"


@router.get("", response_class=HTMLResponse)
@login_required
async def transactions_page(request: Request):
    user = request.session.get("user")
    extras = []
    for key in ("view", "tx_type", "account_id", "target_account_id", "description", "mode", "amount", "credit_bill_id", "add"):
        value = request.query_params.get(key)
        if value:
            extras.append(f"{key}={value}")
    if not request.query_params.get("view"):
        extras.append(f"view={await get_tx_preferred_view(user['user_id'])}")
    suffix = ("?" + "&".join(extras)) if extras else ""
    return RedirectResponse(f"/transactions/list{suffix}", status_code=303)


async def _queue_goal_link_prompt(request: Request, *, user_id: str, transaction_ref, recurring_id) -> None:
    """Investment entries get a one-time "link to a goal?" popup on the next page."""
    if not transaction_ref and not recurring_id:
        return
    try:
        payload = await goal_prompt_for_new_entry(
            user_id,
            transaction_ref=transaction_ref,
            recurring_id=recurring_id,
        )
    except Exception:
        # Optional nicety: never fail a saved transaction over it.
        logger.exception("Goal link prompt check failed")
        return
    set_goal_prompt(request, payload)


@router.get("/add", response_class=HTMLResponse)
@login_required
async def add_transaction_page(request: Request):
    return RedirectResponse(_add_query(request), status_code=303)


@router.post("/add")
@login_required
async def add_transaction(
    request: Request,
    account_id: str = Form(...),
    tx_type: str = Form(...),
    mode: str = Form(...),
    category_code: str = Form(""),
    subcategory_code: str = Form(""),
    amount: float = Form(...),
    description: str = Form(""),
    target_account_id: str | None = Form(None),
    credit_bill_id: str | None = Form(None),
    is_recurring: bool = Form(False),
    frequency: str | None = Form(None),
    interval: int = Form(1),
    start_date: str | None = Form(None),
    end_date: str | None = Form(None),
    transaction_date: str | None = Form(None),
    convert_to_emi: bool = Form(False),
    emi_tenure_months: str | None = Form(None),
    emi_interest_rate: str | None = Form(None),
    emi_processing_fee_rate: str | None = Form(None),
    emi_title: str | None = Form(None),
    csrf_token: str = Form(...),
    return_view: str | None = Form(None),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    emi_conversion = None

    try:
        if _is_recurring_return(return_view):
            is_recurring = True
        if is_recurring and not frequency:
            raise ValidationError("Recurring frequency is required")

        if tx_type in {"transfer", "card_payment"} and not target_account_id:
            raise ValidationError("Target account is required for transfers")

        posted_date = parse_user_date(transaction_date) if transaction_date else None
        if posted_date and posted_date > datetime.now(get_user_timezone(request)).date():
            raise ValidationError("Past transactions cannot be dated in the future.")

        category_code, subcategory_code = resolve_transfer_category_codes(
            tx_type=tx_type,
            category_code=category_code,
            subcategory_code=subcategory_code,
        )
        if not category_code or not subcategory_code:
            raise ValidationError("Category and subcategory are required")

        if convert_to_emi:
            try:
                tenure = int(str(emi_tenure_months or "").strip() or "0")
                roi = float(str(emi_interest_rate or "").strip() or "0")
                processing_rate = float(str(emi_processing_fee_rate or "").strip() or "0")
            except ValueError:
                raise ValidationError("Enter valid EMI tenure, ROI, and processing fee")

            if tenure <= 1:
                raise ValidationError("EMI tenure must be at least 2 months")
            if roi < 0 or processing_rate < 0:
                raise ValidationError("ROI and processing fee cannot be negative")
            emi_conversion = {
                "tenure": tenure,
                "roi": roi,
                "processing_rate": processing_rate,
            }

        effective_type = "transfer" if tx_type == "card_payment" else tx_type
        preview = await categorize_transaction(
            user_id=user["user_id"],
            raw_description=description,
            amount=amount,
            tx_type=effective_type,
            mode=mode,
        )
        category_info, subcategory_info = await validate_category(
            category_code=category_code,
            subcategory_code=subcategory_code,
            tx_type=effective_type,
        )

        created_refs: dict = {}
        created_tx_id = await create_transaction(
            user_id=user["user_id"],
            account_id=account_id,
            target_account_id=target_account_id,
            amount=amount,
            tx_type=tx_type,
            transfer_kind="card_payment" if tx_type == "card_payment" else None,
            credit_bill_id=credit_bill_id,
            mode=mode,
            category_code=category_code,
            subcategory_code=subcategory_code,
            description=description,
            is_recurring=is_recurring,
            frequency=frequency,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            transaction_date=parse_user_date(transaction_date) if transaction_date else None,
            created_refs=created_refs,
            request=request,
        )

        if emi_conversion and created_tx_id:
            await convert_transaction_to_emi(
                user_id=user["user_id"],
                transaction_id=str(created_tx_id),
                tenure_months=int(emi_conversion["tenure"]),
                interest_rate=float(emi_conversion["roi"]),
                processing_fee_rate=float(emi_conversion["processing_rate"]),
                title=emi_title or description,
                request=request,
            )

        if effective_type in {"debit", "credit"} and description.strip():
            suggested_category_code = str(preview.get("suggested_category_code") or "")
            suggested_subcategory_code = str(preview.get("suggested_subcategory_code") or "")
            if (
                not suggested_category_code
                or suggested_category_code != str(category_code)
                or suggested_subcategory_code != str(subcategory_code)
            ):
                await learn_from_override(
                    user_id=user["user_id"],
                    raw_description=description,
                    category=category_info,
                    subcategory=subcategory_info,
                    merchant_name=preview.get("detected_merchant"),
                )
    except AppError as exc:
        return await _add_error_page(
            request,
            error=str(exc.detail),
            status_code=exc.status_code,
            return_view=return_view,
        )
    except Exception:
        return await _add_error_page(
            request,
            error="Unable to add transaction right now. Please retry.",
            status_code=500,
            return_view=return_view,
        )

    await _queue_goal_link_prompt(
        request,
        user_id=user["user_id"],
        transaction_ref=created_tx_id,
        recurring_id=created_refs.get("recurring_id"),
    )

    if _is_recurring_return(return_view):
        flash_msg = "Recurring rule created"
    elif is_recurring:
        flash_msg = "Recurring transaction added"
    elif emi_conversion:
        flash_msg = "Transaction added and converted to EMI"
    elif effective_type == "transfer":
        flash_msg = "Transfer added"
    else:
        flash_msg = "Transaction added"
    return flash_redirect(request, _workspace_url(view=return_view), flash_msg)


# ======================================================
# LIST TRANSACTIONS (BOARD + ALL TABLE)
# ======================================================

async def _load_prepared_transactions(
    *,
    request: Request,
    user: dict,
    account_id: str | None,
    tx_type: str | None,
    date_from: str | None,
    date_to: str | None,
    category_code: str | None,
    subcategory_code: str | None,
    search: str | None,
    amount: str | None,
    sort_by: str | None,
    sort_dir: str | None,
):
    amount_value: float | None = None
    if amount is not None and str(amount).strip() != "":
        try:
            amount_value = float(amount)
        except ValueError:
            amount_value = None

    accounts = await get_accounts(user["user_id"])
    user_tz = get_user_timezone(request)
    account_map = {str(acc["_id"]): acc.get("name") or acc.get("bank_name") or "Account" for acc in accounts}
    account_type_map = {str(acc["_id"]): (acc.get("type") or "") for acc in accounts}
    account_docs = {str(acc["_id"]): acc for acc in accounts}
    search_account_ids = resolve_account_ids_for_search(accounts, search)

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
        sort_by=sort_by or "date",
        sort_dir=sort_dir or "desc",
        account_ids_for_search=search_account_ids or None,
        tz=user_tz,
    )

    transactions = merge_transfer_rows(transactions)

    if sort_by:
        reverse = (sort_dir or "desc").lower() == "desc"

        def sort_key(tx):
            if sort_by == "date":
                return tx.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)
            if sort_by == "amount":
                return tx.get("amount") or 0
            if sort_by == "account":
                aid = str(tx.get("account_id") or tx.get("from_account") or "")
                return account_map.get(aid, "")
            if sort_by == "category":
                cat = tx.get("category") or {}
                return cat.get("name", "") if isinstance(cat, dict) else ""
            if sort_by == "subcategory":
                sub = tx.get("subcategory") or {}
                return sub.get("name", "") if isinstance(sub, dict) else ""
            return tx.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)

        transactions = sorted(transactions, key=sort_key, reverse=reverse)

    transactions = enrich_transactions_for_ui(
        transactions=transactions,
        account_map=account_map,
        account_type_map=account_type_map,
        user_tz=user_tz,
        account_docs=account_docs,
    )

    return {
        "transactions": transactions,
        "accounts": accounts,
        "account_map": account_map,
        "user_tz": user_tz,
    }


async def _render_transactions_workspace(
    request: Request,
    *,
    error: str | None = None,
    open_add: bool = False,
    status_code: int = 200,
    view_override: str | None = None,
):
    user = request.session.get("user")
    user_tz = get_user_timezone(request)
    today_local = datetime.now(user_tz).date()
    account_id = request.query_params.get("account_id")
    tx_type = request.query_params.get("tx_type")
    date_from = request.query_params.get("date_from")
    date_to = request.query_params.get("date_to")
    category_code = request.query_params.get("category_code")
    subcategory_code = request.query_params.get("subcategory_code")
    search = request.query_params.get("search")
    amount = request.query_params.get("amount")
    preferred_view = await get_tx_preferred_view(user["user_id"])
    tx_view = _normalize_tx_view(view_override) or _normalize_tx_view(request.query_params.get("view")) or preferred_view

    prepared = await _load_prepared_transactions(
        request=request,
        user=user,
        account_id=account_id,
        tx_type=tx_type,
        date_from=date_from,
        date_to=date_to,
        category_code=category_code,
        subcategory_code=subcategory_code,
        search=search,
        amount=amount,
        sort_by="date",
        sort_dir="desc",
    )
    notifications = await get_user_notifications(user["user_id"])
    rows = prepared["transactions"]
    # Category filter options (expense + income), de-duplicated by code.
    filter_categories: dict[str, str] = {}
    for kind in ("debit", "credit"):
        for cat in await get_categories_by_type(kind):
            filter_categories.setdefault(cat["code"], cat["name"])
    context = {
        "request": request,
        "user": user,
        "accounts": prepared["accounts"],
        "spend_accounts": _spendable_accounts(prepared["accounts"]),
        "notifications": notifications,
        "view_rows": rows,
        "groups": group_by_local_date(rows, prepared["user_tz"]),
        "columns": build_board_columns(rows, prepared["user_tz"]) if tx_view == "board" else [],
        "kpis": transaction_kpis(rows),
        "filter_categories": sorted(filter_categories.items(), key=lambda kv: kv[1].lower()),
        "filters": {
            "account_id": account_id,
            "tx_type": tx_type,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "category_code": category_code,
            "subcategory_code": subcategory_code,
            "search": search or "",
            "amount": amount or "",
        },
        "active_filter_count": sum(
            1
            for v in [account_id, tx_type, date_from, date_to, category_code, subcategory_code, search, amount]
            if v
        ),
        "tx_defaults": {
            "tx_type": request.query_params.get("tx_type", ""),
            "account_id": request.query_params.get("account_id", ""),
            "target_account_id": request.query_params.get("target_account_id", ""),
            "description": request.query_params.get("description", ""),
            "mode": request.query_params.get("mode", ""),
            "amount": request.query_params.get("amount", ""),
            "credit_bill_id": request.query_params.get("credit_bill_id", ""),
            "transaction_date": request.query_params.get("transaction_date", ""),
        },
        "today_iso": today_local.isoformat(),
        "tx_view": tx_view,
        "tx_preferred_view": preferred_view,
        "error": error,
        "open_add": open_add or request.query_params.get("add") == "1",
        "active_page": "listtransactions",
    }
    return templates.TemplateResponse(
        request=request,
        name="pages/transactions/board.html" if tx_view == "board" else "pages/transactions/list.html",
        context=context,
        status_code=status_code,
    )


@router.get("/list", response_class=HTMLResponse)
@login_required
async def transactions_board_page(request: Request):
    return await _render_transactions_workspace(request)


@router.post("/preferred-view")
@login_required
async def set_transactions_preferred_view(
    request: Request,
    view: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        chosen = await set_tx_preferred_view(user["user_id"], view)
    except RuntimeError:
        chosen = await get_tx_preferred_view(user["user_id"])
    return RedirectResponse(_workspace_url(view=chosen), status_code=303)


@router.get("/all", response_class=HTMLResponse)
@login_required
async def transactions_all_page(
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
    """Full transactions table (all history)."""
    user = request.session.get("user")
    prepared = await _load_prepared_transactions(
        request=request,
        user=user,
        account_id=account_id,
        tx_type=tx_type,
        date_from=date_from,
        date_to=date_to,
        category_code=category_code,
        subcategory_code=subcategory_code,
        search=search,
        amount=amount,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    notifications = await get_user_notifications(user["user_id"])
    transaction_groups = group_by_local_date(prepared["transactions"], prepared["user_tz"])

    def _sort_link(field: str):
        current_dir = (sort_dir or "desc").lower()
        next_dir = "asc" if (sort_by == field and current_dir == "desc") else "desc"
        return str(request.url.include_query_params(sort_by=field, sort_dir=next_dir))

    return templates.TemplateResponse(
        request=request,
        name="pages/transactions/all.html",
        context={
            "request": request,
            "user": user,
            "transactions": prepared["transactions"],
            "transaction_groups": transaction_groups,
            "accounts": prepared["accounts"],
            "account_map": prepared["account_map"],
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
                1
                for v in [account_id, tx_type, date_from, date_to, category_code, subcategory_code, search, amount]
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
            "view_mode": "all",
        },
    )

@router.post("/delete")
@login_required
async def delete_transaction_ui(
    request: Request,
    transaction_id: str = Form(...),
    csrf_token: str = Form(...),
    return_view: str | None = Form(None),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    await delete_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        request=request,
    )

    return flash_redirect(request, _workspace_url(view=return_view), "Transaction deleted")

@router.post("/restore")
@login_required
async def restore_transaction_ui(
    request: Request,
    transaction_id: str = Form(...),
    csrf_token: str = Form(...),
    return_view: str | None = Form(None),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    await restore_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        request=request,
    )

    return flash_redirect(request, _workspace_url(view=return_view), "Transaction restored")

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
    return_view: str | None = Form(None),
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

    return flash_redirect(request, _workspace_url(view=return_view), "Transaction updated")


@router.post("/retry-failed")
@login_required
async def retry_failed_transaction_ui(
    request: Request,
    transaction_id: str = Form(...),
    csrf_token: str = Form(...),
    return_view: str | None = Form(None),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    await retry_failed_recurring_transaction(
        user_id=user["user_id"],
        failed_transaction_id=transaction_id,
        request=request,
    )
    return flash_redirect(request, _workspace_url(view=return_view), "Retry completed")


@router.post("/convert-to-emi")
@login_required
async def convert_existing_transaction_to_emi(
    request: Request,
    transaction_id: str = Form(...),
    emi_tenure_months: int = Form(...),
    emi_interest_rate: float = Form(0.0),
    emi_processing_fee_rate: float = Form(0.0),
    emi_title: str | None = Form(None),
    csrf_token: str = Form(...),
    return_view: str | None = Form(None),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")

    await convert_transaction_to_emi(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        tenure_months=int(emi_tenure_months),
        interest_rate=float(emi_interest_rate),
        processing_fee_rate=float(emi_processing_fee_rate),
        title=emi_title,
        request=request,
    )

    return flash_redirect(request, _workspace_url(view=return_view), "Transaction converted to EMI")
