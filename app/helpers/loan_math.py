"""Reducing-balance loan math. No database access."""

from __future__ import annotations

import calendar
import math
from datetime import date

from dateutil.relativedelta import relativedelta

from app.helpers.money import round_money


def monthly_rate(annual_rate: float | None) -> float:
    return float(annual_rate or 0) / 12.0 / 100.0


def monthly_interest(outstanding: float, annual_rate: float | None) -> float:
    return round_money(max(float(outstanding or 0), 0) * monthly_rate(annual_rate))


def suggested_emi(principal: float, annual_rate: float | None, tenure_months: int | None) -> float:
    principal = max(float(principal or 0), 0)
    months = int(tenure_months or 0)
    if principal <= 0 or months <= 0:
        return 0.0
    rate = monthly_rate(annual_rate)
    if rate <= 0:
        return round_money(principal / months)
    factor = (1 + rate) ** months
    return round_money(principal * rate * factor / (factor - 1))


def suggested_tenure(principal: float, annual_rate: float | None, emi_amount: float | None) -> int:
    principal = max(float(principal or 0), 0)
    emi = max(float(emi_amount or 0), 0)
    if principal <= 0 or emi <= 0:
        return 0
    rate = monthly_rate(annual_rate)
    if rate <= 0:
        return max(1, int(math.ceil(principal / emi - 1e-9)))
    if emi <= principal * rate + 0.005:
        return 0
    months = math.log(emi / (emi - principal * rate)) / math.log(1 + rate)
    return max(1, int(round(months)))


def clamp_day(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(int(day or 1), 1), last))


def next_emi_date(from_day: date, emi_day: int, *, inclusive: bool = True) -> date:
    candidate = clamp_day(from_day.year, from_day.month, emi_day)
    if inclusive and candidate >= from_day:
        return candidate
    if not inclusive and candidate > from_day:
        return candidate
    nxt = from_day + relativedelta(months=1)
    return clamp_day(nxt.year, nxt.month, emi_day)


def apply_emi_cycle(
    *,
    outstanding: float,
    emi_amount: float,
    annual_rate: float | None,
) -> dict:
    """Add monthly interest, then deduct the EMI. Interest first, then principal."""
    opening = round_money(max(float(outstanding or 0), 0))
    emi = round_money(max(float(emi_amount or 0), 0))
    if opening <= 0:
        return {
            "opening": 0.0,
            "interest": 0.0,
            "principal": 0.0,
            "payment": 0.0,
            "outstanding": 0.0,
            "closed": True,
        }
    interest = monthly_interest(opening, annual_rate)
    after_interest = round_money(opening + interest)
    payment = round_money(min(emi if emi > 0 else after_interest, after_interest))
    interest_portion = round_money(min(interest, payment))
    principal_portion = round_money(payment - interest_portion)
    closing = round_money(after_interest - payment)
    if closing < 0.005:
        closing = 0.0
    return {
        "opening": opening,
        "interest": interest_portion,
        "principal": principal_portion,
        "payment": payment,
        "outstanding": closing,
        "closed": closing <= 0,
    }


def loan_certificate(loan: dict) -> dict:
    original = round_money(loan.get("original_principal") or loan.get("balance") or 0)
    outstanding = round_money(max(float(loan.get("balance") or 0), 0))
    interest_paid = round_money(loan.get("interest_paid") or 0)
    principal_paid = round_money(loan.get("principal_paid") or 0)
    emis_paid = int(loan.get("emis_paid") or 0)
    return {
        "original_principal": original,
        "outstanding": outstanding,
        "principal_paid": principal_paid,
        "interest_paid": interest_paid,
        "total_paid": round_money(principal_paid + interest_paid),
        "emis_paid": emis_paid,
        "interest_rate": round_money(loan.get("interest_rate") or 0),
        "emi_amount": round_money(loan.get("emi_amount") or 0),
        "tenure_months": loan.get("tenure_months"),
        "emi_day": int(loan.get("emi_day") or 0) or None,
        "status": "closed" if outstanding <= 0 else (loan.get("loan_status") or "active"),
    }


def emi_conversion_details(*, amount: float, tenure: int, roi: float, processing_rate: float) -> dict[str, float]:
    """Card-spend-to-EMI figures: fee is charged upfront and financed with the principal."""
    processing_fee_amount = round(float(amount) * (float(processing_rate) / 100.0), 2)
    financed_amount = round(float(amount) + processing_fee_amount, 2)
    monthly_rate_value = float(roi) / 12.0 / 100.0
    if monthly_rate_value <= 0:
        monthly_amount = financed_amount / tenure
        total_payable = financed_amount
    else:
        factor = math.pow(1 + monthly_rate_value, tenure)
        monthly_amount = financed_amount * monthly_rate_value * factor / (factor - 1)
        total_payable = monthly_amount * tenure
    monthly_amount = round(monthly_amount, 2)
    total_payable = round(total_payable, 2)
    estimated_interest = round(max(total_payable - financed_amount, 0.0), 2)
    return {
        "processing_fee_amount": processing_fee_amount,
        "financed_amount": financed_amount,
        "monthly_amount": monthly_amount,
        "estimated_interest": estimated_interest,
    }
