from datetime import date

from fastapi import APIRouter, Request, Form
from app.core.csrf import verify_csrf_token
from app.core.errors import AppError, ValidationError
from app.core.time import parse_user_date
from app.web.templates import templates
from app.core.guards import login_required
from app.helpers.accounts_ui import enrich_account_row, holdings_kpis, loan_kind_choices
from app.helpers.flash import flash_redirect
from app.services.loans import apply_due_loan_cycles, get_loan_certificate, pay_loan_emi, update_loan_settings
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
from app.services.credit_cards import get_credit_card_account_insights, generate_bill_snapshot_for_account, update_bill


router = APIRouter()

ACCOUNT_TYPES = [
    ("savings", "Savings"),
    ("current", "Current"),
    ("credit_card", "Credit Card"),
    ("wallet", "Wallet"),
    ("cash", "Cash"),
    ("investment", "Investment"),
    ("loan", "Loan"),
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
    parsed = parse_user_date(raw)
    if parsed is None:
        raise ValidationError("Enter a valid date")
    return parsed


async def _build_accounts_context(request: Request, user: dict, *, error: str | None = None):
    await apply_due_loan_cycles(user_id=user["user_id"], request=request)
    accounts = await get_accounts(user["user_id"])
    credit_cards = [acc for acc in accounts if acc.get("type") == "credit_card"]
    loan_accounts = [acc for acc in accounts if acc.get("type") == "loan"]
    regular_accounts = [acc for acc in accounts if acc.get("type") not in {"credit_card", "loan"}]
    today = date.today()
    holdings = [enrich_account_row(acc, today=today) for acc in accounts]
    certificates = {}
    for loan in loan_accounts:
        try:
            certificates[str(loan.get("_id"))] = await get_loan_certificate(
                user_id=user["user_id"],
                account_id=str(loan.get("_id")),
            )
        except Exception:
            certificates[str(loan.get("_id"))] = None
    credit_card_emis = await get_credit_card_emi_map(user["user_id"])
    credit_card_insights = await get_credit_card_account_insights(user_id=user["user_id"])
    return {
        "request": request,
        "user": user,
        "error": error,
        "accounts": accounts,
        "holdings": holdings,
        "kpis": holdings_kpis(holdings),
        "regular_accounts": regular_accounts,
        "credit_cards": credit_cards,
        "loan_accounts": loan_accounts,
        "loan_certificates": certificates,
        "credit_card_emis": credit_card_emis,
        "credit_card_insights": credit_card_insights,
        "account_types": ACCOUNT_TYPES,
        "card_networks": CARD_NETWORKS,
        "loan_kinds": loan_kind_choices(),
        "notifications": await get_user_notifications(user["user_id"]),
        "active_page": "accounts",
        "open_view": request.query_params.get("view"),
        "holdings_group": request.query_params.get("group"),
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
        name="/pages/accounts/accounts.html",
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
    original_principal: str | None = Form(None),
    interest_rate: str | None = Form(None),
    emi_amount: str | None = Form(None),
    emi_day: str | None = Form(None),
    tenure_months: str | None = Form(None),
    start_date: str | None = Form(None),
    last4: str | None = Form(None),
    loan_kind: str | None = Form(None),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        created_account_id = await create_account(
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
            original_principal=_parse_optional_float(original_principal),
            interest_rate=_parse_optional_float(interest_rate),
            emi_amount=_parse_optional_float(emi_amount),
            emi_day=_parse_optional_int(emi_day, label="EMI day"),
            tenure_months=_parse_optional_int(tenure_months, label="tenure"),
            start_date=_parse_optional_date(start_date),
            last4=last4,
            loan_kind=loan_kind,
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    kind_label = {
        "credit_card": "Credit card added",
        "loan": "Loan added",
    }.get(acc_type, "Account added")
    return flash_redirect(
        request,
        f"/accounts?created=1&kind={acc_type}&id={created_account_id}&balance={balance}",
        kind_label,
    )


# ======================================================
# RENAME ACCOUNT (NAME ONLY)
# ======================================================

@router.post("/rename")
@login_required
async def rename_account(
    request: Request,
    account_id: str = Form(...),
    name: str = Form(...),
    last4: str | None = Form(None),
    bank_name: str | None = Form(None),
    acc_type: str | None = Form(None),
    balance: str | None = Form(None),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await update_account_name(
            user_id=user["user_id"],
            account_id=account_id,
            name=name,
            last4=last4,
            bank_name=bank_name,
            acc_type=acc_type,
            balance=_parse_optional_float(balance),
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return flash_redirect(request, "/accounts", "Account updated")


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

    return flash_redirect(request, "/accounts", "Account balance updated")


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
    last4: str | None = Form(None),
    name: str | None = Form(None),
    bank_name: str | None = Form(None),
    outstanding: str | None = Form(None),
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
            last4=last4,
            name=name,
            bank_name=bank_name,
            outstanding=_parse_optional_float(outstanding),
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return flash_redirect(request, "/accounts", "Credit card updated")


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
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return flash_redirect(request, "/accounts", "Credit card bill generated")


@router.post("/credit-card/bill/update")
@login_required
async def update_credit_card_bill(
    request: Request,
    account_id: str = Form(...),
    bill_id: str = Form(...),
    final_amount: str | None = Form(None),
    minimum_due: str | None = Form(None),
    due_date: str | None = Form(None),
    note: str | None = Form(None),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")

    def _parse_float(raw: str | None) -> float | None:
        if raw is None:
            return None
        val = str(raw).strip()
        if not val:
            return None
        return float(val)

    class _Payload:
        def __init__(self, *, final_amount=None, minimum_due=None, due_date=None, note=None):
            self.final_amount = final_amount
            self.minimum_due = minimum_due
            self.due_date = due_date
            self.note = note

    try:
        payload = _Payload(
            final_amount=_parse_float(final_amount),
            minimum_due=_parse_float(minimum_due),
            due_date=_parse_optional_date(due_date),
            note=(note or "").strip() or None,
        )
        await update_bill(
            user_id=user["user_id"],
            card_id=account_id,
            bill_id=bill_id,
            payload=payload,
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )
    except ValueError:
        return templates.TemplateResponse(
            request=request,
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error="Enter valid amounts for bill correction"),
            status_code=400,
        )

    return flash_redirect(request, "/accounts", "Credit card bill updated")


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
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return flash_redirect(request, "/accounts", "EMI added")


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
            name="/pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return flash_redirect(request, "/accounts", "EMI updated")


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
            name="/pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return flash_redirect(request, "/accounts", "EMI deleted")


@router.post("/loan/update")
@login_required
async def edit_loan(
    request: Request,
    account_id: str = Form(...),
    name: str | None = Form(None),
    interest_rate: str | None = Form(None),
    emi_amount: str | None = Form(None),
    emi_day: str | None = Form(None),
    tenure_months: str | None = Form(None),
    last4: str | None = Form(None),
    loan_kind: str | None = Form(None),
    bank_name: str | None = Form(None),
    original_principal: str | None = Form(None),
    outstanding: str | None = Form(None),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await update_loan_settings(
            user_id=user["user_id"],
            account_id=account_id,
            name=name,
            interest_rate=_parse_optional_float(interest_rate),
            emi_amount=_parse_optional_float(emi_amount),
            emi_day=_parse_optional_int(emi_day, label="EMI day"),
            tenure_months=_parse_optional_int(tenure_months, label="tenure"),
            last4=last4,
            loan_kind=loan_kind,
            bank_name=bank_name,
            original_principal=_parse_optional_float(original_principal),
            outstanding=_parse_optional_float(outstanding),
            request=request,
        )
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )
    return flash_redirect(request, "/accounts", "Loan updated")


@router.post("/loan/pay-emi")
@login_required
async def record_loan_emi(
    request: Request,
    account_id: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await pay_loan_emi(user_id=user["user_id"], account_id=account_id, request=request)
    except AppError as e:
        return templates.TemplateResponse(
            request=request,
            name="pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )
    return flash_redirect(request, "/accounts?view=" + account_id, "EMI payment recorded")


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
            name="/pages/accounts/accounts.html",
            context=await _build_accounts_context(request, user, error=str(e)),
            status_code=e.status_code,
        )

    return flash_redirect(request, "/accounts", "Account deleted")
