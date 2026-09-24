"""JSON APIs for the smart transaction inbox."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.core.guards import login_required
from app.services.transaction_inbox import (
    approve_inbox_item,
    bulk_approve_inbox_items,
    get_pending_inbox_items,
    reject_inbox_item,
)

router = APIRouter()


def _json_error(exc: AppError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@router.get("/inbox")
@login_required
async def list_inbox(request: Request, needs_attention: bool = False):
    user = request.session.get("user")
    try:
        return await get_pending_inbox_items(
            user_id=user["user_id"],
            only_attention=needs_attention,
        )
    except AppError as exc:
        return _json_error(exc)


@router.post("/inbox/approve/{row_id}")
@login_required
async def approve_inbox(request: Request, row_id: str):
    user = request.session.get("user")
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    try:
        return await approve_inbox_item(
            user_id=user["user_id"],
            row_id=row_id,
            request=request,
            amount=payload.get("amount"),
            description=payload.get("description"),
            tx_type=payload.get("type"),
            mode=payload.get("mode"),
            category_code=payload.get("category_code"),
            subcategory_code=payload.get("subcategory_code"),
            statement_date=payload.get("txn_date") or payload.get("date"),
        )
    except AppError as exc:
        return _json_error(exc)


@router.post("/inbox/reject/{row_id}")
@login_required
async def reject_inbox(request: Request, row_id: str):
    user = request.session.get("user")
    try:
        return await reject_inbox_item(
            user_id=user["user_id"],
            row_id=row_id,
        )
    except AppError as exc:
        return _json_error(exc)


@router.post("/inbox/bulk-approve")
@login_required
async def bulk_approve_inbox(request: Request):
    user = request.session.get("user")
    payload = await request.json()
    try:
        return await bulk_approve_inbox_items(
            user_id=user["user_id"],
            row_ids=[str(row_id) for row_id in (payload.get("row_ids") or [])],
            request=request,
        )
    except AppError as exc:
        return _json_error(exc)
