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
    approve_high_confidence_rows,
    approve_inbox_rows,
    clear_pending_buffer,
    clear_sms_buffer,
    discard_inbox_rows,
    import_statement_to_inbox,
    ingest_sms_to_inbox,
    list_inbox_rows,
    parse_sms_buffer_to_inbox,
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
        # Return detailed pipeline report
        return JSONResponse({
            "success": result.get("stage3_inserted", 0) > 0,
            "parsed": result.get("stage1_parsed", 0),
            "normalized": result.get("stage2_normalized", 0),
            "sample": result.get("stage2_sample", []),
            "inserted": result.get("stage3_inserted", 0),
            "duplicates": result.get("stage3_duplicates", 0),
            "needs_attention": result.get("stage3_needs_attention", 0),
            "statement_total": result.get("statement_total", 0),
            "inbox_total": result.get("inbox_total", 0),
            "stage1_errors": result.get("stage1_errors", [])[:5],
            "stage2_errors": result.get("stage2_errors", [])[:5],
            "stage3_errors": result.get("stage3_errors", [])[:5],
            "detail": (
                f"Parsed {result.get('stage1_parsed', 0)} rows, "
                f"normalized {result.get('stage2_normalized', 0)}, "
                f"inserted {result.get('stage3_inserted', 0)} to inbox"
            )
        })
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
            subcategory_code=payload.get("subcategory_code"),
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


@router.post("/transaction-inbox/approve-high-confidence")
@login_required
async def transaction_inbox_approve_high_confidence(request: Request):
    payload = await request.json()
    verify_csrf_token(request, payload.get("csrf_token"))
    user = request.session.get("user")
    try:
        result = await approve_high_confidence_rows(
            user_id=user["user_id"],
            min_confidence=int(payload.get("min_confidence") or 70),
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


@router.post("/transaction-inbox/sms/ingest")
@login_required
async def transaction_inbox_sms_ingest(request: Request):
    payload = await request.json()
    verify_csrf_token(request, payload.get("csrf_token"))
    user = request.session.get("user")
    try:
        result = await ingest_sms_to_inbox(
            user_id=user["user_id"],
            account_id=str(payload.get("account_id") or ""),
            messages=list(payload.get("messages") or []),
        )
        return JSONResponse(result)
    except AppError as exc:
        return _json_error(exc)


@router.post("/transaction-inbox/sms/sync-buffer")
@login_required
async def transaction_inbox_sms_sync_buffer(
    request: Request,
    account_id: str = Form(...),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        result = await parse_sms_buffer_to_inbox(
            user_id=user["user_id"],
            account_id=account_id,
        )
        return JSONResponse(result)
    except AppError as exc:
        return _json_error(exc)


@router.post("/transaction-inbox/sms/clear-buffer")
@login_required
async def transaction_inbox_sms_clear_buffer(request: Request):
    payload = await request.json()
    verify_csrf_token(request, payload.get("csrf_token"))
    user = request.session.get("user")
    try:
        result = await clear_sms_buffer(user_id=user["user_id"])
        return JSONResponse(result)
    except AppError as exc:
        return _json_error(exc)


@router.post("/transaction-inbox/buffer/clear")
@login_required
async def transaction_inbox_clear_pending_buffer(request: Request):
    payload = await request.json()
    verify_csrf_token(request, payload.get("csrf_token"))
    user = request.session.get("user")
    try:
        result = await clear_pending_buffer(user_id=user["user_id"])
        return JSONResponse({"cleared_count": result.get("cleared_count", 0)})
    except AppError as exc:
        return _json_error(exc)
