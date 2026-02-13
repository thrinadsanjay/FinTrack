from datetime import date, datetime

from app.db.mongo import db


def parse_date_value(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    raise Exception("Invalid date value")


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
