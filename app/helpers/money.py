from decimal import Decimal, ROUND_HALF_UP


def round_money(value: float | int | str | Decimal | None) -> float:
    if value is None:
        return 0.0
    dec = Decimal(str(value))
    return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
