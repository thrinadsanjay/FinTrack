"""
UI controller for the transaction inbox.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.csrf import verify_csrf_token
from app.core.errors import AppError
from app.services.accounts import get_accounts
from app.services.dashboard import get_user_notifications
from app.services.transaction_inbox import (
    approve_inbox_rows,
    discard_inbox_rows,
    import_statement_to_inbox,
    list_inbox_rows,
    update_inbox_row,
)
from app.web.templates import templates
from app.core.guards import login_required

router = APIRouter()


def _json_error(exc: AppError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@router.get("/transaction-inbox", response_class=HTMLResponse)
@login_required
async def transaction_inbox_page(request: Request):
    user = request.session.get("user")
    accounts = await get_accounts(user["user_id"])
    notifications = await get_user_notifications(user["user_id"])
    return templates.TemplateResponse(
        request=request,
        name="transaction_inbox.html",
        context={
            "request": request,
            "user": user,
            "accounts": accounts,
            "notifications": notifications,
            "active_page": "transactioninbox",
        },
    )


@router.get("/transaction-inbox/list")
@login_required
async def transaction_inbox_list(
    request: Request,
    needs_attention: bool = False,
):
    user = request.session.get("user")
    try:
        return await list_inbox_rows(
            user_id=user["user_id"],
            only_attention=needs_attention,
        )
    except AppError as exc:
        return _json_error(exc)


@router.post("/transaction-inbox/upload-statement")
@login_required
async def transaction_inbox_upload_statement(
    request: Request,
    account_id: str = Form(...),
    csrf_token: str = Form(...),
    statement_file: UploadFile = File(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        result = await import_statement_to_inbox(
            user_id=user["user_id"],
            account_id=account_id,
            upload=statement_file,
        )
        return JSONResponse(result)
    except AppError as exc:
        return _json_error(exc)


@router.post("/transaction-inbox/update-row")
@login_required
async def transaction_inbox_update_row(
    request: Request,
):
    payload = await request.json()
    verify_csrf_token(request, payload.get("csrf_token"))
    user = request.session.get("user")
    try:
        row = await update_inbox_row(
            user_id=user["user_id"],
            row_id=str(payload.get("row_id") or ""),
            amount=payload.get("amount"),
            description=payload.get("description"),
            tx_type=payload.get("type"),
            mode=payload.get("mode"),
            category_code=payload.get("category_code"),
            statement_date=payload.get("date"),
        )
        return JSONResponse({"row": row})
    except AppError as exc:
        return _json_error(exc)


@router.post("/transaction-inbox/approve")
@login_required
async def transaction_inbox_approve(request: Request):
    payload = await request.json()
    verify_csrf_token(request, payload.get("csrf_token"))
    user = request.session.get("user")
    try:
        result = await approve_inbox_rows(
            user_id=user["user_id"],
            row_ids=[str(row_id) for row_id in (payload.get("row_ids") or [])],
            request=request,
        )
        return JSONResponse(result)
    except AppError as exc:
        return _json_error(exc)


@router.post("/transaction-inbox/discard")
@login_required
async def transaction_inbox_discard(request: Request):
    payload = await request.json()
    verify_csrf_token(request, payload.get("csrf_token"))
    user = request.session.get("user")
    try:
        result = await discard_inbox_rows(
            user_id=user["user_id"],
            row_ids=[str(row_id) for row_id in (payload.get("row_ids") or [])],
        )
        return JSONResponse(result)
    except AppError as exc:
        return _json_error(exc)
