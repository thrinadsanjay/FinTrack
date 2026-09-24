from datetime import date, datetime

from app.db.mongo import db

TRANSFER_CATEGORY_CODE = "transfer"
TRANSFER_SUBCATEGORY_CODE = "transfer"


def parse_date_value(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    raise Exception("Invalid date value")


def resolve_transfer_category_codes(
    *,
    tx_type: str,
    category_code: str | None = None,
    subcategory_code: str | None = None,
) -> tuple[str, str]:
    if tx_type in {"transfer", "card_payment"}:
        return TRANSFER_CATEGORY_CODE, TRANSFER_SUBCATEGORY_CODE
    return (category_code or "").strip(), (subcategory_code or "").strip()


async def validate_category(*, category_code: str, subcategory_code: str, tx_type: str):
    category = await db.categories.find_one(
        {"code": category_code, "type": tx_type, "is_system": True}
    )
    if not category:
        raise Exception("Invalid category")

    sub = next(
        (s for s in category["subcategories"] if s["code"] == subcategory_code),
        None,
    )
    if not sub:
        raise Exception("Invalid subcategory")

    return (
        {"code": category["code"], "name": category["name"]},
        {"code": sub["code"], "name": sub["name"]},
    )
