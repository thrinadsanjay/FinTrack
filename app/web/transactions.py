from bson import ObjectId
from fastapi import APIRouter, Request, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from app.services.accounts import get_accounts
from app.web.templates import templates
from app.db.mongo import db
from app.services.transactions import create_transaction, get_user_transactions, delete_transaction, edit_transaction

router = APIRouter()

@router.get("", response_class=HTMLResponse)
async def transactions_page(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    accounts = await get_accounts(user["user_id"])

    return templates.TemplateResponse(
        "transactions_add.html",
        {
            "request": request,
            "user": user,
            "accounts": accounts,
            "active_page": "addtransaction",
        },
    )

@router.post("/add")
async def add_transaction(
    request: Request,
    account_id: str = Form(...),
    tx_type: str = Form(...),
    category_code: str = Form(...),
    subcategory_code: str = Form(...),
    amount: float = Form(...),
    description: str = Form(""),
    target_account_id: str | None = Form(None),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    await create_transaction(
        user_id=user["user_id"],
        account_id=account_id,
        target_account_id=target_account_id,
        amount=amount,
        tx_type=tx_type,
        category_code=category_code,
        subcategory_code=subcategory_code,
        description=description,
        request=request,
    )

    return RedirectResponse("/transactions", status_code=303)


@router.get("/list", response_class=HTMLResponse)
async def transactions_list_page(
    request: Request,
    account_id: str | None = Query(None),
    tx_type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    category_code: str | None = Query(None),
    subcategory_code: str | None = Query(None),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    transactions = await get_user_transactions(
        user_id=user["user_id"],
        account_id=account_id,
        tx_type=tx_type,
        date_from=date_from,
        date_to=date_to,
        category_code=category_code,
        subcategory_code=subcategory_code,
    )

    accounts = await get_accounts(user["user_id"])
    account_map = {str(acc["_id"]): acc["name"] for acc in accounts}

    return templates.TemplateResponse(
        "transactions_list.html",
        {
            "request": request,
            "user": user,
            "transactions": transactions,
            "accounts": accounts,
            "account_map": account_map,
            "filters": {
                "account_id": account_id,
                "tx_type": tx_type,
                "date_from": date_from,
                "date_to": date_to,
                "category_code": category_code,
                "subcategory_code": subcategory_code,
            },
            "active_page": "listtransactions",
        },
    )

@router.post("/delete")
async def delete_transaction_route(
    request: Request,
    transaction_id: str = Form(...),
    transfer_id: str | None = Form(None),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)
    
    if not transaction_id and not transfer_id:
        raise Exception("Missing delete identifier")

    await delete_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        transfer_id=transfer_id,
        request=request,
    )

    return RedirectResponse("/transactions/list", status_code=303)

# @router.get("/edit/{transaction_id}", response_class=HTMLResponse)
# async def edit_transaction_page(request: Request, transaction_id: str):
#     user = request.session.get("user")
#     if not user:
#         return RedirectResponse("/login", status_code=303)

#     tx = await db.transactions.find_one(
#         {"_id": ObjectId(transaction_id), "user_id": ObjectId(user["user_id"])}
#     )

#     if not tx or tx.get("transfer_id"):
#         return RedirectResponse("/transactions/list", status_code=303)

#     accounts = await get_accounts(user["user_id"])

#     return templates.TemplateResponse(
#         "transaction_edit.html",
#         {
#             "request": request,
#             "transaction": tx,
#             "accounts": accounts,
#         },
#     )

@router.post("/edit")
async def edit_transaction_submit(
    request: Request,
    transaction_id: str = Form(...),
    account_id: str = Form(...),
    amount: float = Form(...),
    category_code: str = Form(...),
    subcategory_code: str = Form(...),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

    await edit_transaction(
        user_id=user["user_id"],
        transaction_id=transaction_id,
        new_account_id=account_id,
        new_amount=amount,
        new_category_code=category_code,
        new_subcategory_code=subcategory_code,
        request=request,
    )

    return RedirectResponse("/transactions/list", status_code=303)

