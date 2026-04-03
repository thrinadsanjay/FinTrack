from datetime import date

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from app.core.csrf import verify_csrf_token
from app.core.errors import AppError, ValidationError
from app.web.templates import templates
from app.core.guards import login_required
from app.services.accounts import (
    get_accounts,
    create_account,
    update_account_name,
    update_account_balance,
    update_credit_card_settings,
    get_credit_card_emi_map,
    add_credit_card_emi,
    update_credit_card_emi,
    delete_credit_card_emi,
    delete_account,
)
from app.services.dashboard import get_user_notifications
from app.services.credit_cards import get_credit_card_account_insights, generate_bill_snapshot_for_account


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

CARD_NETWORKS = [
    ("visa", "Visa"),
    ("mastercard", "Mastercard"),
    ("rupay", "RuPay"),
    ("amex", "AmEx"),
    ("diners", "Diners"),
    ("other", "Other"),
]


def _parse_optional_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValidationError("Enter a valid amount") from exc



def _parse_optional_int(raw: str | None, *, label: str) -> int | None:
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError(f"Enter a valid {label}") from exc



def _parse_optional_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError("Enter a valid date") from exc


async def _build_accounts_context(request: Request, user: dict, *, error: str | None = None):
    accounts = await get_accounts(user["user_id"])
    credit_cards = [acc for acc in accounts if acc.get("type") == "credit_card"]
    regular_accounts = [acc for acc in accounts if acc.get("type") != "credit_card"]
    credit_card_emis = await get_credit_card_emi_map(user["user_id"])
    credit_card_insights = await get_credit_card_account_insights(user_id=user["user_id"])
    return {
        "request": request,
        "user": user,
        "error": error,
        "accounts": accounts,
        "regular_accounts": regular_accounts,
        "credit_cards": credit_cards,
        "credit_card_emis": credit_card_emis,
        "credit_card_insights": credit_card_insights,
        "account_types": ACCOUNT_TYPES,
        "card_networks": CARD_NETWORKS,
        "notifications": await get_user_notifications(user["user_id"]),
        "active_page": "accounts",
    }


# ======================================================
# LIST ACCOUNTS
# ======================================================

@router.get("")
@login_required
async def accounts_page(request: Request):
    user = request.session.get("user")
    context = await _build_accounts_context(request, user)
    return templates.TemplateResponse(
        request=request,
        name="accounts.html",
        context=context,
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
    credit_limit: str | None = Form(None),
    minimum_due: str | None = Form(None),
    statement_balance: str | None = Form(None),
    card_network: str | None = Form(None),
    billing_cycle_start_day: str | None = Form(None),
    billing_cycle_end_day: str | None = Form(None),
    due_day: str | None = Form(None),
    bill_generation_date: str | None = Form(None),
    payment_due_date: str | None = Form(None),
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
            credit_limit=_parse_optional_float(credit_limit),
            minimum_due=_parse_optional_float(minimum_due),
            statement_balance=_parse_optional_float(statement_balance),
            card_network=card_network,
            billing_cycle_start_day=_parse_optional_int(billing_cycle_start_day, label="billing cycle start day"),
            billing_cycle_end_day=_parse_optional_int(billing_cycle_end_day, label="billing cycle end day"),
            due_day=_parse_optional_int(due_day, label="due day"),
            bill_generation_date=_parse_optional_date(bill_generation_date),
            payment_due_date=_parse_optional_date(payment_due_date),
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
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


@router.post("/credit-card/update")
@login_required
async def edit_credit_card(
    request: Request,
    account_id: str = Form(...),
    credit_limit: str | None = Form(None),
    minimum_due: str | None = Form(None),
    statement_balance: str | None = Form(None),
    card_network: str | None = Form(None),
    billing_cycle_start_day: str | None = Form(None),
    billing_cycle_end_day: str | None = Form(None),
    due_day: str | None = Form(None),
    bill_generation_date: str | None = Form(None),
    payment_due_date: str | None = Form(None),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await update_credit_card_settings(
            user_id=user["user_id"],
            account_id=account_id,
            credit_limit=_parse_optional_float(credit_limit),
            minimum_due=_parse_optional_float(minimum_due),
            statement_balance=_parse_optional_float(statement_balance),
            card_network=card_network,
            billing_cycle_start_day=_parse_optional_int(billing_cycle_start_day, label="billing cycle start day"),
            billing_cycle_end_day=_parse_optional_int(billing_cycle_end_day, label="billing cycle end day"),
            due_day=_parse_optional_int(due_day, label="due day"),
            bill_generation_date=_parse_optional_date(bill_generation_date),
            payment_due_date=_parse_optional_date(payment_due_date),
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/credit-card/generate-bill")
@login_required
async def generate_credit_card_bill(
    request: Request,
    account_id: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await generate_bill_snapshot_for_account(
            user_id=user["user_id"],
            account_id=account_id,
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/credit-card/emi/add")
@login_required
async def create_credit_card_emi(
    request: Request,
    account_id: str = Form(...),
    title: str = Form(...),
    total_amount: float = Form(...),
    monthly_amount: float = Form(...),
    total_installments: str = Form(...),
    remaining_installments: str = Form(...),
    interest_rate: str | None = Form(None),
    next_due_date: str | None = Form(None),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        total_installments_value = _parse_optional_int(total_installments, label="installment count")
        remaining_installments_value = _parse_optional_int(remaining_installments, label="remaining installment count")
        if total_installments_value is None or remaining_installments_value is None:
            raise ValidationError("Installment counts are required")
        await add_credit_card_emi(
            user_id=user["user_id"],
            account_id=account_id,
            title=title,
            total_amount=total_amount,
            monthly_amount=monthly_amount,
            total_installments=total_installments_value,
            remaining_installments=remaining_installments_value,
            interest_rate=_parse_optional_float(interest_rate),
            next_due_date=_parse_optional_date(next_due_date),
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/credit-card/emi/update")
@login_required
async def edit_credit_card_emi(
    request: Request,
    emi_id: str = Form(...),
    title: str = Form(...),
    total_amount: float = Form(...),
    monthly_amount: float = Form(...),
    total_installments: str = Form(...),
    remaining_installments: str = Form(...),
    interest_rate: str | None = Form(None),
    next_due_date: str | None = Form(None),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        total_installments_value = _parse_optional_int(total_installments, label="installment count")
        remaining_installments_value = _parse_optional_int(remaining_installments, label="remaining installment count")
        if total_installments_value is None or remaining_installments_value is None:
            raise ValidationError("Installment counts are required")
        await update_credit_card_emi(
            user_id=user["user_id"],
            emi_id=emi_id,
            title=title,
            total_amount=total_amount,
            monthly_amount=monthly_amount,
            total_installments=total_installments_value,
            remaining_installments=remaining_installments_value,
            interest_rate=_parse_optional_float(interest_rate),
            next_due_date=_parse_optional_date(next_due_date),
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return RedirectResponse("/accounts", status_code=303)


@router.post("/credit-card/emi/delete")
@login_required
async def remove_credit_card_emi(
    request: Request,
    emi_id: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await delete_credit_card_emi(
            user_id=user["user_id"],
            emi_id=emi_id,
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
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
            request=request,
            name="accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return RedirectResponse("/accounts", status_code=303)
