"""Web endpoints for categorization preview."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.csrf import verify_csrf_token
from app.core.errors import AppError
from app.core.guards import login_required
from app.services.categorization_engine import categorize_transaction

router = APIRouter()
logger = logging.getLogger(__name__)


async def _run_categorization_preview(
    *,
    user_id: str,
    raw_description: str,
    tx_type: str,
    mode: str,
    amount: float,
):
    return await categorize_transaction(
        user_id=user_id,
        raw_description=raw_description,
        amount=amount,
        tx_type="transfer" if tx_type == "card_payment" else tx_type,
        mode=mode,
    )


@router.get("/categorize-preview")
@login_required
async def categorize_preview_get(request: Request):
    user = request.session.get("user")
    raw_description = str(request.query_params.get("raw_description") or request.query_params.get("description") or "").strip()
    tx_type = str(request.query_params.get("tx_type") or "debit")
    mode = str(request.query_params.get("mode") or "unknown")

    try:
        amount = float(request.query_params.get("amount") or 0)
        logger.info(
            "categorize_preview GET request: user_id=%s tx_type=%s mode=%s amount=%.2f raw_description=%s",
            str(user.get("user_id")),
            tx_type,
            mode,
            amount,
            raw_description,
        )
        result = await _run_categorization_preview(
            user_id=user["user_id"],
            raw_description=raw_description,
            tx_type=tx_type,
            mode=mode,
            amount=amount,
        )
        logger.info(
            "categorize_preview GET response: user_id=%s suggested_category_code=%s suggested_subcategory_code=%s confidence_percent=%s",
            str(user.get("user_id")),
            result.get("suggested_category_code"),
            result.get("suggested_subcategory_code"),
            result.get("confidence_percent"),
        )
        return JSONResponse(result)
    except AppError as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@router.post("/categorize-preview")
@login_required
async def categorize_preview(request: Request):
    payload = await request.json()
    verify_csrf_token(request, payload.get("csrf_token"))
    user = request.session.get("user")
    raw_description = str(payload.get("raw_description") or payload.get("description") or "").strip()
    tx_type = str(payload.get("tx_type") or "debit")
    mode = str(payload.get("mode") or "unknown")

    try:
        amount = float(payload.get("amount") or 0)
        logger.info(
            "categorize_preview POST request: user_id=%s tx_type=%s mode=%s amount=%.2f raw_description=%s",
            str(user.get("user_id")),
            tx_type,
            mode,
            amount,
            raw_description,
        )
        result = await _run_categorization_preview(
            user_id=user["user_id"],
            raw_description=raw_description,
            tx_type=tx_type,
            mode=mode,
            amount=amount,
        )
        logger.info(
            "categorize_preview POST response: user_id=%s suggested_category_code=%s suggested_subcategory_code=%s confidence_percent=%s",
            str(user.get("user_id")),
            result.get("suggested_category_code"),
            result.get("suggested_subcategory_code"),
            result.get("confidence_percent"),
        )
        return JSONResponse(result)
    except AppError as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
