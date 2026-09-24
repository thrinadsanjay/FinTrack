"""Map institution names to real bank logos."""

from __future__ import annotations

BRANDS = (
    {"key": "icici", "logo": "/static/icons/banks/icici.svg?v=3", "match": ("icici",)},
    {"key": "hdfc", "logo": "/static/icons/banks/hdfc.svg?v=3", "match": ("hdfc",)},
    {"key": "kotak", "logo": "/static/icons/banks/kotak.svg?v=3", "match": ("kotak",)},
    {"key": "sbi", "logo": "/static/icons/banks/sbi.svg?v=3", "match": ("sbi", "state bank")},
    {"key": "axis", "logo": "/static/icons/banks/axis.svg?v=3", "match": ("axis",)},
    {"key": "yes", "logo": "/static/icons/banks/yes.svg?v=3", "match": ("yes bank", "yesbank")},
    {"key": "idfc", "logo": "/static/icons/banks/idfc.svg?v=3", "match": ("idfc",)},
    {"key": "bob", "logo": "/static/icons/banks/bob.svg?v=3", "match": ("baroda", "bob")},
    {"key": "pnb", "logo": "/static/icons/banks/pnb.svg?v=3", "match": ("pnb", "punjab national")},
    {"key": "indusind", "logo": "/static/icons/banks/generic-bank.svg?v=3", "match": ("indusind",)},
    {"key": "paytm", "logo": "/static/icons/banks/generic-wallet.svg?v=3", "match": ("paytm",)},
)

FALLBACKS = {
    "card": {"key": "card", "logo": "/static/icons/banks/generic-card.svg?v=3"},
    "loan": {"key": "loan", "logo": "/static/icons/banks/generic-loan.svg?v=3"},
    "wallet": {"key": "wallet", "logo": "/static/icons/banks/generic-wallet.svg?v=3"},
    "bank": {"key": "bank", "logo": "/static/icons/banks/generic-bank.svg?v=3"},
}


def resolve_bank_brand(account: dict, *, group: str | None = None) -> dict:
    text = f"{account.get('bank_name') or ''} {account.get('name') or ''}".lower()
    for brand in BRANDS:
        if any(token in text for token in brand["match"]):
            return dict(brand)
    return dict(FALLBACKS.get(group or "bank", FALLBACKS["bank"]))
