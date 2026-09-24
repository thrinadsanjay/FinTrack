from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def round_money(value: float | int | str | Decimal | None) -> float:
    """Normalize a monetary value to 2 decimal places.

    Tolerates None/blank, Jinja Undefined, Decimal, and BSON Decimal128-like values.
    """
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 0.0

    # Jinja2 Undefined / Missing values
    if type(value).__name__ in {"Undefined", "StrictUndefined", "ChainableUndefined", "DebugUndefined"}:
        return 0.0
    if getattr(value, "_undefined_name", None) is not None and not isinstance(value, (int, float, str, Decimal)):
        # Avoid treating legitimate types as undefined; Jinja Undefined sets this.
        try:
            bool(value)  # Undefined raises or is falsy depending on type
        except Exception:
            return 0.0

    if isinstance(value, str) and not value.strip():
        return 0.0

    # bson.Decimal128 exposes to_decimal()
    to_decimal = getattr(value, "to_decimal", None)
    if callable(to_decimal):
        try:
            value = to_decimal()
        except Exception:
            return 0.0

    try:
        if isinstance(value, Decimal):
            dec = value
        elif isinstance(value, (int, float)):
            if value != value:  # NaN
                return 0.0
            dec = Decimal(str(value))
        else:
            text = str(value).strip().replace(",", "")
            if not text or text.lower() in {"none", "null", "nan", "undefined"}:
                return 0.0
            # Guard against "Decimal128('1.00')" style strings
            if text.startswith("Decimal128("):
                return 0.0
            dec = Decimal(text)
        if not dec.is_finite():
            return 0.0
        return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError, ArithmeticError):
        return 0.0


def format_inr_digits(value: float | int | str | Decimal | None) -> str:
    """Indian-grouped amount without the rupee sign (e.g. 1,93,108.00)."""
    amount = round_money(value)
    negative = amount < 0
    amount = abs(amount)
    whole = int(amount)
    fraction = int(round((amount - whole) * 100))
    if fraction >= 100:
        whole += 1
        fraction = 0
    text = f"{_indian_group(whole)}.{fraction:02d}"
    return f"-{text}" if negative else text


def format_inr(value: float | int | str | Decimal | None, *, paise: bool = True) -> str:
    """Format a rupee amount with Indian grouping (e.g. ₹1,93,108.00)."""
    digits = format_inr_digits(value)
    if digits.startswith("-"):
        return f"-₹{digits[1:]}"
    return f"₹{digits}"


def _indian_group(whole: int) -> str:
    digits = str(abs(int(whole)))
    if len(digits) <= 3:
        return digits
    last3 = digits[-3:]
    rest = digits[:-3]
    parts: list[str] = []
    while len(rest) > 2:
        parts.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.append(rest)
    return ",".join(reversed(parts)) + "," + last3
