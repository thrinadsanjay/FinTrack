"""Presentation helpers for the Accounts holdings table."""

from __future__ import annotations

from datetime import date

from app.helpers.bank_brands import resolve_bank_brand
from app.helpers.labels import account_type_label
from app.helpers.money import round_money
from app.helpers.loan_math import loan_certificate, next_emi_date
from app.helpers.planning_math import credit_card_available, credit_card_outstanding, as_date

TYPE_META = {
    "savings": {"icon": "fa-building-columns", "group": "bank", "kind": "account"},
    "current": {"icon": "fa-building-columns", "group": "bank", "kind": "account"},
    "wallet": {"icon": "fa-wallet", "group": "bank", "kind": "wallet"},
    "cash": {"icon": "fa-money-bill", "group": "bank", "kind": "wallet"},
    "investment": {"icon": "fa-chart-line", "group": "bank", "kind": "account"},
    "other": {"icon": "fa-building-columns", "group": "bank", "kind": "account"},
    "credit_card": {"icon": "fa-credit-card", "group": "card", "kind": "credit_card"},
    "loan": {"icon": "fa-file-invoice-dollar", "group": "loan", "kind": "loan"},
}

LOAN_KINDS = {
    "home": {"label": "Home Loan", "icon": "fa-house-chimney"},
    "personal": {"label": "Personal Loan", "icon": "fa-user"},
    "auto": {"label": "Auto Loan", "icon": "fa-car"},
    "two_wheeler": {"label": "Two-wheeler Loan", "icon": "fa-motorcycle"},
    "education": {"label": "Education Loan", "icon": "fa-graduation-cap"},
    "gold": {"label": "Gold Loan", "icon": "fa-gem"},
    "business": {"label": "Business Loan", "icon": "fa-briefcase"},
    "lap": {"label": "Loan Against Property", "icon": "fa-building"},
    "credit": {"label": "Credit Card Loan", "icon": "fa-credit-card"},
    "other": {"label": "Other Loan", "icon": "fa-file-invoice-dollar"},
}

_LOAN_KIND_HINTS = (
    ("two wheeler", "two_wheeler"),
    ("two-wheeler", "two_wheeler"),
    ("credit card loan", "credit"),
    ("against property", "lap"),
    ("home loan", "home"),
    ("housing", "home"),
    ("personal", "personal"),
    ("auto loan", "auto"),
    ("car loan", "auto"),
    ("education", "education"),
    ("gold loan", "gold"),
    ("business", "business"),
)

CARD_NETWORK_LABELS = {
    "visa": "Visa",
    "mastercard": "Mastercard",
    "rupay": "RuPay",
    "amex": "AmEx",
    "diners": "Diners",
    "other": "Other",
}

def _as_date(value) -> date | None:
    return as_date(value)


def type_meta(acc_type: str | None) -> dict:
    return TYPE_META.get((acc_type or "").strip().lower(), TYPE_META["other"])


def loan_kind_choices() -> list[tuple[str, str, str]]:
    return [(key, meta["label"], meta["icon"]) for key, meta in LOAN_KINDS.items()]


def normalize_loan_kind(value: str | None, *, name: str | None = None) -> str:
    text = str(name or "").lower()
    for token, kind in _LOAN_KIND_HINTS:
        if token in text:
            return kind
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in LOAN_KINDS:
        return key
    aliases = {
        "home_loan": "home",
        "housing": "home",
        "personal_loan": "personal",
        "car": "auto",
        "car_loan": "auto",
        "auto_loan": "auto",
        "two_wheeler_loan": "two_wheeler",
        "education_loan": "education",
        "gold_loan": "gold",
        "business_loan": "business",
        "loan_against_property": "lap",
        "credit_card_loan": "credit",
        "other_loan": "other",
    }
    if key in aliases:
        return aliases[key]
    stored = str(value or "").lower()
    for token, kind in _LOAN_KIND_HINTS:
        if token in stored:
            return kind
    return "other"


def loan_kind_meta(value: str | None, *, name: str | None = None) -> dict:
    kind = normalize_loan_kind(value, name=name)
    meta = LOAN_KINDS[kind]
    return {"key": kind, "label": meta["label"], "icon": meta["icon"]}


def card_network_label(value: str | None) -> str:
    key = str(value or "").strip().lower()
    if key in CARD_NETWORK_LABELS:
        return CARD_NETWORK_LABELS[key]
    return key.replace("_", " ").title() if key else "—"


def account_mask(account: dict) -> str:
    last4 = "".join(ch for ch in str(account.get("last4") or "") if ch.isdigit())
    if len(last4) == 4:
        return f"•• {last4}"
    return "*"


def enrich_account_row(account: dict, *, today: date | None = None) -> dict:
    row = dict(account)
    today = today or date.today()
    acc_type = str(row.get("type") or "other").strip().lower()
    meta = type_meta(acc_type)
    row["id"] = str(row.get("_id") or row.get("id") or "")
    row["type_key"] = acc_type
    row["type_label"] = account_type_label(acc_type)
    row["type_icon"] = meta["icon"]
    row["group"] = meta["group"]
    row["kind"] = meta["kind"]
    row["display_name"] = row.get("name") or row.get("bank_name") or "Account"
    row["mask"] = account_mask(row)
    brand = resolve_bank_brand(row, group=meta["group"])
    row["brand_key"] = brand["key"]
    row["logo_url"] = brand["logo"]
    row["last4"] = "".join(ch for ch in str(row.get("last4") or "") if ch.isdigit())[:4]
    row["institution"] = row.get("bank_name") or row["display_name"]
    row["card_network_label"] = card_network_label(row.get("card_network"))

    if acc_type == "credit_card":
        outstanding = credit_card_outstanding(row)
        limit = round_money(row.get("credit_limit") or 0)
        available = credit_card_available(row)
        util = round_money((outstanding / limit) * 100) if limit else None
        row["display_amount"] = outstanding
        row["amount_kind"] = "liability"
        row["amount_label"] = "Outstanding"
        row["activity_label"] = _due_label(row.get("payment_due_date") or row.get("due_day"), today)
        if util is None:
            row["status_key"] = "healthy"
            row["status_label"] = "Healthy"
        elif util >= 50:
            row["status_key"] = "watch"
            row["status_label"] = "Watch"
        else:
            row["status_key"] = "healthy"
            row["status_label"] = "Healthy"
        row["utilization"] = util
        row["row_alert"] = row["status_key"] == "watch"
        row["available_credit"] = available
        row["outstanding"] = outstanding
        row["credit_limit"] = limit
        row["view_facts"] = [
            {"label": "Issuer", "value": row["institution"]},
            {"label": "Network", "value": row["card_network_label"]},
            {"label": "Card number", "value": row["mask"]},
            {"label": "Credit limit", "value": limit, "money": True},
            {"label": "Available credit", "value": available, "money": True},
            {"label": "Utilisation", "value": f"{util:.1f}%" if util is not None else "—"},
            {"label": "Payment due", "value": row["activity_label"]},
            {"label": "Status", "value": row["status_label"]},
        ]
    elif acc_type == "loan":
        kind = loan_kind_meta(row.get("loan_kind"), name=row["display_name"])
        cert = loan_certificate(row)
        next_due = _as_date(row.get("next_due_date"))
        row["loan_kind"] = kind["key"]
        row["type_label"] = kind["label"]
        row["type_icon"] = kind["icon"]
        row["display_amount"] = cert["outstanding"]
        row["amount_kind"] = "liability"
        row["amount_label"] = "Outstanding"
        row["emi_amount"] = round_money(row.get("emi_amount") or 0)
        row["activity_label"] = f"EMI {next_due.strftime('%d %b %Y')}" if next_due else "No EMI date"
        row["activity_secondary"] = next_due.strftime("%d %b %Y") if next_due else None
        if cert["outstanding"] <= 0:
            row["status_key"] = "healthy"
            row["status_label"] = "Closed"
        elif next_due and next_due < today:
            row["status_key"] = "watch"
            row["status_label"] = "Overdue"
        else:
            row["status_key"] = "healthy"
            row["status_label"] = "On track"
        row["row_alert"] = row["status_key"] == "watch"
        row["utilization"] = None
        row["certificate"] = cert
        row["next_due"] = next_due
        row["next_due_label"] = next_due.strftime("%d %b %Y") if next_due else "—"
        row["view_facts"] = [
            {"label": "Lender", "value": row["institution"]},
            {"label": "Loan type", "value": kind["label"]},
            {"label": "Account", "value": row["mask"]},
            {"label": "Interest rate", "value": f"{round_money(row.get('interest_rate') or 0)}% p.a."},
            {"label": "EMI amount", "value": row.get("emi_amount") or 0, "money": True},
            {"label": "Next EMI", "value": row["next_due_label"]},
            {"label": "Tenure", "value": f"{row.get('tenure_months')} months" if row.get("tenure_months") else "—"},
            {"label": "Status", "value": row["status_label"]},
        ]
    else:
        updated = _as_date(row.get("updated_at") or row.get("created_at"))
        row["display_amount"] = round_money(row.get("balance") or 0)
        row["amount_kind"] = "asset"
        row["amount_label"] = "Available balance"
        row["activity_label"] = updated.strftime("%d %b %Y") if updated else "—"
        row["status_key"] = "healthy"
        row["status_label"] = "Healthy"
        row["row_alert"] = False
        row["utilization"] = None
        row["view_facts"] = [
            {"label": "Institution", "value": row["institution"]},
            {"label": "Account type", "value": row["type_label"]},
            {"label": "Account", "value": row["mask"]},
            {"label": "Last activity", "value": row["activity_label"]},
            {"label": "Status", "value": row["status_label"]},
        ]
    return row


def _due_label(value, today: date) -> str:
    due = _as_date(value)
    if due:
        return f"{due.strftime('%d %b %Y')} due"
    if isinstance(value, int):
        nxt = next_emi_date(today, value, inclusive=True)
        return f"{nxt.strftime('%d %b %Y')} due"
    return "—"


def holdings_kpis(rows: list[dict]) -> dict:
    cash = cards_out = credit_avail = loans = 0.0
    bank_count = card_count = loan_count = 0
    util_weight = 0.0
    util_base = 0.0
    for row in rows:
        group = row.get("group")
        if group == "bank":
            cash += float(row.get("display_amount") or 0)
            bank_count += 1
        elif group == "card":
            cards_out += float(row.get("outstanding") or 0)
            credit_avail += float(row.get("available_credit") or 0)
            card_count += 1
            limit = float(row.get("credit_limit") or 0)
            if limit:
                util_weight += float(row.get("outstanding") or 0)
                util_base += limit
        elif group == "loan":
            loans += float(row.get("display_amount") or 0)
            loan_count += 1
    util = round_money((util_weight / util_base) * 100) if util_base else 0.0
    return {
        "total_cash": round_money(cash),
        "card_outstanding": round_money(cards_out),
        "available_credit": round_money(credit_avail),
        "loans_outstanding": round_money(loans),
        "utilization": util,
        "bank_count": bank_count,
        "card_count": card_count,
        "loan_count": loan_count,
    }
