from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import re

from bson import ObjectId

from app.db.mongo import db
from app.services.categories import get_categories_by_type, get_subcategories
from app.services.transactions import create_transaction
from app.services.telegram import send_message


SESSION_COLLECTION = "telegram_tx_sessions"
BOT_COMMAND_ADD = "/addtransaction"
BOT_COMMAND_CANCEL = "/cancel"
BOT_COMMAND_LAST5 = "/last5"
BOT_COMMAND_BALANCE = "/balance"
BOT_COMMAND_SUMMARY = "/summary"
_AMOUNT_REGEX = re.compile(r"(?<!\w)(\d+(?:\.\d{1,2})?)(?!\w)")
_FROM_ACCOUNT_REGEX = re.compile(r"\bfrom\s+([a-z0-9][a-z0-9 _\-]{1,40})\b", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def _to_float(raw: str) -> float | None:
    try:
        value = float(str(raw).replace(",", "").strip())
    except Exception:
        return None
    if value <= 0:
        return None
    return round(value, 2)


def _build_keyboard(options: list[str], per_row: int = 2) -> dict:
    rows: list[list[dict]] = []
    row: list[dict] = []
    for item in options:
        row.append({"text": item})
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def _quick_keyboard(*, include_cancel: bool = True) -> dict:
    buttons = ["Add Transaction", "Last 5 Transactions", "Balance", "Summary", "Help"]
    if include_cancel:
        buttons.append("Cancel")
    return _build_keyboard(buttons, per_row=2)


@dataclass
class TxOption:
    label: str
    value: str


def _options_to_payload(options: list[TxOption]) -> list[dict]:
    return [{"label": o.label, "value": o.value} for o in options]


def _resolve_option(raw: str, options: list[dict]) -> str | None:
    token = _normalize(raw)
    for item in options:
        if token == _normalize(item.get("label")):
            return str(item.get("value") or "")
        if token == _normalize(item.get("value")):
            return str(item.get("value") or "")
    return None


async def _load_session(*, chat_id: str) -> dict | None:
    return await db[SESSION_COLLECTION].find_one({"chat_id": chat_id})


async def _save_session(*, chat_id: str, user_id: ObjectId, step: str, data: dict, options: list[dict] | None = None) -> None:
    now = _now()
    await db[SESSION_COLLECTION].update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "user_id": user_id,
                "step": step,
                "data": data,
                "options": options or [],
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def _clear_session(*, chat_id: str) -> None:
    await db[SESSION_COLLECTION].delete_one({"chat_id": chat_id})


async def _send_text(*, bot_token: str, chat_id: str, text: str, options: list[str] | None = None) -> None:
    reply_markup = _quick_keyboard()
    if options:
        reply_markup = _build_keyboard(options + ["Cancel"], per_row=2)
    await send_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
    )


async def _send_help(*, bot_token: str, chat_id: str) -> None:
    await send_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=(
            "FinTracker Telegram Help\n\n"
            "Available options:\n"
            "1) /start - Show welcome and quick actions.\n"
            "2) /help - Show this help message.\n"
            "3) /addtransaction - Start transaction entry flow.\n"
            "4) Add Transaction - Same as /addtransaction.\n"
            "5) /last5 - Show last 5 transactions.\n"
            "6) Last 5 Transactions - Same as /last5.\n"
            "7) /balance - Show total and account-wise balances.\n"
            "8) Balance - Same as /balance.\n"
            "9) /summary - Show current month summary.\n"
            "10) Summary - Same as /summary.\n"
            "11) /cancel - Cancel the current transaction flow.\n"
            "12) Cancel - Same as /cancel.\n\n"
            "Quick entry:\n"
            "- Send text like: '100 swiggy order from kotak'\n"
            "- Bot will auto-detect type/category/subcategory/account and ask for confirmation.\n\n"
            "Transaction flow:\n"
            "Type -> Category -> Subcategory -> Account -> Mode -> Amount -> Description -> Confirm"
        ),
        reply_markup=_quick_keyboard(),
    )


def _infer_type(text: str) -> str:
    t = _normalize(text)
    credit_keywords = {
        "salary", "refund", "interest", "cashback", "bonus", "income", "credited", "credit",
    }
    if any(k in t for k in credit_keywords):
        return "credit"
    return "debit"


def _infer_mode(text: str) -> str:
    t = _normalize(text)
    if "card" in t or "debit card" in t or "credit card" in t:
        return "card"
    if "cash" in t:
        return "other"
    if "netbanking" in t or "bank transfer" in t or "imps" in t or "neft" in t:
        return "online"
    if "upi" in t or "gpay" in t or "phonepe" in t or "paytm" in t:
        return "upi"
    return "upi"


def _extract_amount(text: str) -> float | None:
    m = _AMOUNT_REGEX.search(text or "")
    if not m:
        return None
    return _to_float(m.group(1))


def _extract_account_hint(text: str) -> str:
    m = _FROM_ACCOUNT_REGEX.search(text or "")
    return str((m.group(1) if m else "") or "").strip()


def _normalize_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _normalize(text))
    return set(words)


def _clean_description(text: str) -> str:
    raw = str(text or "").strip()
    raw = _AMOUNT_REGEX.sub("", raw, count=1)
    raw = _FROM_ACCOUNT_REGEX.sub("", raw, count=1)
    raw = re.sub(r"\s+", " ", raw).strip(" -,:")
    return raw or "Telegram entry"


async def _pick_account(user_id: ObjectId, raw_text: str) -> dict | None:
    accounts = await db.accounts.find(
        {"user_id": user_id, "deleted_at": None},
        {"name": 1, "balance": 1},
    ).to_list(length=200)
    if not accounts:
        return None

    full_text = _normalize(raw_text)
    text_words = _normalize_words(raw_text)

    # 1) Prefer explicit "from <account>" hint.
    hint = _normalize(_extract_account_hint(raw_text))
    if hint:
        best = None
        best_score = -1
        for acc in accounts:
            name = _normalize(str(acc.get("name") or ""))
            score = 0
            if hint == name:
                score = 120
            elif hint in name:
                score = 90
            elif any(part and part in name for part in hint.split()):
                score = 60
            if score > best_score:
                best_score = score
                best = acc
        if best is not None and best_score > 0:
            return best

    # 2) Infer from any account/bank word mentioned in text.
    best = None
    best_score = -1
    for acc in accounts:
        name = str(acc.get("name") or "")
        norm_name = _normalize(name)
        name_words = _normalize_words(name)
        score = 0
        if norm_name and norm_name in full_text:
            score += 120
        overlap = len(text_words & name_words)
        score += overlap * 25
        # Prefer bank/account hints if present.
        if any(w in text_words for w in {"hdfc", "kotak", "sbi", "icici", "axis", "idfc"}):
            if any(bank in norm_name for bank in {"hdfc", "kotak", "sbi", "icici", "axis", "idfc"}):
                score += 20
        if score > best_score:
            best_score = score
            best = acc
    if best is not None and best_score > 0:
        return best

    return sorted(accounts, key=lambda a: str(a.get("name") or "").lower())[0]


async def _pick_category_subcategory(tx_type: str, description: str) -> tuple[dict, dict] | tuple[None, None]:
    categories = await db.categories.find(
        {"type": tx_type, "is_system": True},
        {"code": 1, "name": 1, "subcategories": 1},
    ).to_list(length=200)
    if not categories:
        return None, None

    text = _normalize(description)
    words = _normalize_words(description)

    # Domain shortcuts first.
    keyword_preferences = [
        ({"swiggy", "zomato", "food", "restaurant", "dine", "order"}, {"food", "dining", "dineout"}),
        ({"uber", "ola", "taxi", "cab", "fuel", "petrol"}, {"travel", "transport"}),
        ({"amazon", "flipkart", "shopping", "store"}, {"shopping"}),
        ({"rent", "landlord"}, {"rent", "housing"}),
        ({"movie", "netflix", "prime", "hotstar"}, {"entertainment"}),
        ({"hospital", "medical", "medicine", "medicines", "meds", "pharmacy", "doctor"}, {"health", "medical", "pharmacy"}),
    ]

    def cat_matches(cat_name: str, prefs: set[str]) -> bool:
        n = _normalize(cat_name)
        return any(p in n for p in prefs)

    for trigger_words, pref_cats in keyword_preferences:
        if any(w in text for w in trigger_words):
            for cat in categories:
                if not cat_matches(str(cat.get("name") or ""), pref_cats):
                    continue
                subs = list(cat.get("subcategories") or [])
                preferred_sub = None
                for sub in subs:
                    sub_name = _normalize(str(sub.get("name") or ""))
                    if any(p in sub_name for p in pref_cats):
                        preferred_sub = sub
                        break
                selected_sub = preferred_sub or (subs[0] if subs else None)
                if selected_sub:
                    return cat, selected_sub

    # Name-token similarity fallback.
    best_cat = None
    best_cat_score = -1
    for cat in categories:
        cat_words = _normalize_words(str(cat.get("name") or ""))
        score = len(words & cat_words)
        if score > best_cat_score:
            best_cat_score = score
            best_cat = cat

    if best_cat is None:
        best_cat = categories[0]

    subs = list(best_cat.get("subcategories") or [])
    if not subs:
        return None, None

    best_sub = subs[0]
    best_sub_score = -1
    for sub in subs:
        sub_words = _normalize_words(str(sub.get("name") or ""))
        score = len(words & sub_words)
        if score > best_sub_score:
            best_sub_score = score
            best_sub = sub
    return best_cat, best_sub


async def _try_quick_transaction_detect(user_id: ObjectId, raw_text: str) -> dict | None:
    amount = _extract_amount(raw_text)
    if not amount:
        return None

    tx_type = _infer_type(raw_text)
    description = _clean_description(raw_text)
    category, subcategory = await _pick_category_subcategory(tx_type, description)
    if not category or not subcategory:
        return None

    account = await _pick_account(user_id, raw_text)
    if not account:
        return None

    mode = _infer_mode(raw_text)
    return {
        "tx_type": tx_type,
        "category_code": str(category.get("code") or ""),
        "category_name": str(category.get("name") or ""),
        "subcategory_code": str(subcategory.get("code") or ""),
        "subcategory_name": str(subcategory.get("name") or ""),
        "account_id": str(account.get("_id") or ""),
        "account_name": f"{str(account.get('name') or 'Account')} (₹{float(account.get('balance') or 0):.2f})",
        "mode": mode,
        "amount": float(amount),
        "description": description,
    }


def _fmt_tx_time(value: datetime | None) -> str:
    if not value:
        return "-"
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d %b %I:%M %p")


def _tx_display_type(tx_type: str) -> str:
    t = str(tx_type or "").lower()
    if t == "credit":
        return "Income"
    if t == "debit":
        return "Expense"
    if t in {"transfer", "transfer_out", "transfer_in"}:
        return "Transfer"
    return t or "Transaction"


async def _send_last_transactions(*, bot_token: str, chat_id: str, user_id: ObjectId) -> None:
    txs = await db.transactions.find(
        {"user_id": user_id, "deleted_at": None},
        {"type": 1, "amount": 1, "description": 1, "created_at": 1, "account_id": 1, "is_failed": 1},
    ).sort("created_at", -1).limit(5).to_list(length=5)
    if not txs:
        await send_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text="No transactions found yet.",
            reply_markup=_quick_keyboard(),
        )
        return

    account_ids = [t.get("account_id") for t in txs if t.get("account_id")]
    account_map: dict[str, str] = {}
    if account_ids:
        accounts = await db.accounts.find({"_id": {"$in": account_ids}}, {"name": 1}).to_list(length=200)
        account_map = {str(a["_id"]): str(a.get("name") or "Account") for a in accounts}

    lines = ["Last 5 transactions:"]
    for idx, tx in enumerate(txs, start=1):
        amount = float(tx.get("amount") or 0)
        tx_type = _tx_display_type(str(tx.get("type") or ""))
        account_name = account_map.get(str(tx.get("account_id") or ""), "Account")
        desc = str(tx.get("description") or "").strip() or "-"
        status = " (failed)" if bool(tx.get("is_failed")) else ""
        lines.append(
            f"{idx}) {tx_type} ₹{amount:.2f} | {account_name} | {desc} | {_fmt_tx_time(tx.get('created_at'))}{status}"
        )

    await send_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=_quick_keyboard(),
    )


async def _send_balances(*, bot_token: str, chat_id: str, user_id: ObjectId) -> None:
    accounts = await db.accounts.find(
        {"user_id": user_id, "deleted_at": None},
        {"name": 1, "balance": 1},
    ).sort("name", 1).to_list(length=200)
    if not accounts:
        await send_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text="No accounts found.",
            reply_markup=_quick_keyboard(),
        )
        return

    total = sum(float(a.get("balance") or 0) for a in accounts)
    lines = [f"Total balance: ₹{total:.2f}", "", "Per account:"]
    for a in accounts:
        lines.append(f"- {str(a.get('name') or 'Account')}: ₹{float(a.get('balance') or 0):.2f}")

    await send_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=_quick_keyboard(),
    )


async def _send_summary(*, bot_token: str, chat_id: str, user_id: ObjectId) -> None:
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    pipeline = [
        {
            "$match": {
                "user_id": user_id,
                "deleted_at": None,
                "created_at": {"$gte": month_start},
                "is_failed": {"$ne": True},
            }
        },
        {"$group": {"_id": "$type", "total": {"$sum": {"$ifNull": ["$amount", 0]}}, "count": {"$sum": 1}}},
    ]
    rows = await db.transactions.aggregate(pipeline).to_list(length=10)
    by_type = {str(r.get("_id") or ""): r for r in rows}
    income = float((by_type.get("credit") or {}).get("total") or 0)
    expense = float((by_type.get("debit") or {}).get("total") or 0)
    transfer = float((by_type.get("transfer_out") or {}).get("total") or 0) + float((by_type.get("transfer_in") or {}).get("total") or 0)
    count = sum(int(r.get("count") or 0) for r in rows)
    net = income - expense

    text = (
        f"Summary for {month_start.strftime('%b %Y')}:\n"
        f"- Transactions: {count}\n"
        f"- Income: ₹{income:.2f}\n"
        f"- Expense: ₹{expense:.2f}\n"
        f"- Transfers: ₹{transfer:.2f}\n"
        f"- Net: ₹{net:.2f}"
    )
    await send_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        reply_markup=_quick_keyboard(),
    )


async def _begin_flow(*, bot_token: str, chat_id: str, user_id: ObjectId) -> None:
    options = [
        TxOption("Income", "credit"),
        TxOption("Expense", "debit"),
        TxOption("Transfer", "transfer"),
    ]
    await _save_session(
        chat_id=chat_id,
        user_id=user_id,
        step="type",
        data={},
        options=_options_to_payload(options),
    )
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text="Select transaction type:",
        options=[o.label for o in options],
    )


async def _ask_category(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    tx_type = str(data.get("tx_type") or "")
    categories = await get_categories_by_type(tx_type)
    options = [TxOption(c["name"], c["code"]) for c in categories]
    if not options:
        await _clear_session(chat_id=chat_id)
        await _send_text(
            bot_token=bot_token,
            chat_id=chat_id,
            text="No categories configured for this type. Please contact admin.",
        )
        return
    await _save_session(
        chat_id=chat_id,
        user_id=user_id,
        step="category",
        data=data,
        options=_options_to_payload(options),
    )
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text="Select category:",
        options=[o.label for o in options],
    )


async def _ask_subcategory(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    tx_type = str(data.get("tx_type") or "")
    category_code = str(data.get("category_code") or "")
    subs = await get_subcategories(category_code=category_code, tx_type=tx_type) or []
    options = [TxOption(str(s.get("name") or ""), str(s.get("code") or "")) for s in subs if s.get("code")]
    if not options:
        await _clear_session(chat_id=chat_id)
        await _send_text(
            bot_token=bot_token,
            chat_id=chat_id,
            text="No subcategories found for selected category.",
        )
        return
    await _save_session(
        chat_id=chat_id,
        user_id=user_id,
        step="subcategory",
        data=data,
        options=_options_to_payload(options),
    )
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text="Select subcategory:",
        options=[o.label for o in options],
    )


async def _ask_account(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    accounts = await db.accounts.find(
        {"user_id": user_id, "deleted_at": None},
        {"name": 1, "balance": 1},
    ).sort("name", 1).to_list(length=100)
    options = [
        TxOption(f"{str(a.get('name') or 'Account')} (₹{float(a.get('balance') or 0):.2f})", str(a["_id"]))
        for a in accounts
    ]
    if not options:
        await _clear_session(chat_id=chat_id)
        await _send_text(
            bot_token=bot_token,
            chat_id=chat_id,
            text="No active accounts available. Create an account first.",
        )
        return
    await _save_session(
        chat_id=chat_id,
        user_id=user_id,
        step="account",
        data=data,
        options=_options_to_payload(options),
    )
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text="Select source account:",
        options=[o.label for o in options],
    )


async def _ask_target_account(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    source_id = str(data.get("account_id") or "")
    accounts = await db.accounts.find(
        {"user_id": user_id, "deleted_at": None, "_id": {"$ne": ObjectId(source_id)}},
        {"name": 1},
    ).sort("name", 1).to_list(length=100)
    options = [TxOption(str(a.get("name") or "Account"), str(a["_id"])) for a in accounts]
    if not options:
        await _clear_session(chat_id=chat_id)
        await _send_text(
            bot_token=bot_token,
            chat_id=chat_id,
            text="No target account available for transfer.",
        )
        return
    await _save_session(
        chat_id=chat_id,
        user_id=user_id,
        step="target_account",
        data=data,
        options=_options_to_payload(options),
    )
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text="Select target account:",
        options=[o.label for o in options],
    )


async def _ask_mode(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    options = [
        TxOption("UPI", "upi"),
        TxOption("Card", "card"),
        TxOption("Online", "online"),
        TxOption("Other", "other"),
    ]
    await _save_session(
        chat_id=chat_id,
        user_id=user_id,
        step="mode",
        data=data,
        options=_options_to_payload(options),
    )
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text="Select transaction mode:",
        options=[o.label for o in options],
    )


async def _ask_amount(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    await _save_session(chat_id=chat_id, user_id=user_id, step="amount", data=data, options=[])
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text="Enter amount (example: 1234.50):",
    )


async def _ask_description(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    await _save_session(chat_id=chat_id, user_id=user_id, step="description", data=data, options=[])
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text="Enter description, or type 'skip':",
    )


async def _ask_confirm(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    summary = (
        "Please confirm transaction:\n"
        f"- Type: {data.get('tx_type')}\n"
        f"- Category: {data.get('category_name')}\n"
        f"- Subcategory: {data.get('subcategory_name')}\n"
        f"- Account: {data.get('account_name')}\n"
        + (f"- Target: {data.get('target_account_name')}\n" if data.get("target_account_name") else "")
        + f"- Mode: {data.get('mode')}\n"
        + f"- Amount: ₹{float(data.get('amount') or 0):.2f}\n"
        + f"- Description: {data.get('description') or '-'}"
    )
    options = [TxOption("Confirm", "confirm"), TxOption("Cancel", "cancel")]
    await _save_session(
        chat_id=chat_id,
        user_id=user_id,
        step="confirm",
        data=data,
        options=_options_to_payload(options),
    )
    await _send_text(
        bot_token=bot_token,
        chat_id=chat_id,
        text=summary,
        options=[o.label for o in options],
    )


async def _finalize_transaction(*, bot_token: str, chat_id: str, user_id: ObjectId, data: dict) -> None:
    tx_id = await create_transaction(
        user_id=str(user_id),
        account_id=str(data["account_id"]),
        amount=float(data["amount"]),
        tx_type=str(data["tx_type"]),
        mode=str(data["mode"]),
        category_code=str(data["category_code"]),
        subcategory_code=str(data["subcategory_code"]),
        description=str(data.get("description") or ""),
        target_account_id=str(data["target_account_id"]) if data.get("target_account_id") else None,
        is_recurring=False,
        request=None,
    )
    await _clear_session(chat_id=chat_id)
    await send_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=f"Transaction added successfully. Ref: {tx_id}",
        reply_markup=_quick_keyboard(),
    )


async def process_telegram_text(*, bot_token: str, chat_id: str, text: str) -> None:
    raw = str(text or "").strip()
    normalized = _normalize(raw)

    user = await db.users.find_one(
        {"telegram_chat_id": chat_id, "deleted_at": None},
        {"_id": 1, "is_active": 1},
    )
    if not user:
        await send_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text="This Telegram account is not linked to any FinTracker user. Please link from Profile first.",
            reply_markup=_quick_keyboard(),
        )
        return
    if not bool(user.get("is_active", True)):
        await send_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text="Your account is disabled. Contact admin.",
            reply_markup=_quick_keyboard(),
        )
        return

    user_id = user["_id"]
    if normalized in {"/start", "/help"}:
        await _send_help(bot_token=bot_token, chat_id=chat_id)
        return

    if normalized in {BOT_COMMAND_LAST5, "last 5 transactions", "last5"}:
        await _send_last_transactions(bot_token=bot_token, chat_id=chat_id, user_id=user_id)
        return

    if normalized in {BOT_COMMAND_BALANCE, "balance"}:
        await _send_balances(bot_token=bot_token, chat_id=chat_id, user_id=user_id)
        return

    if normalized in {BOT_COMMAND_SUMMARY, "summary"}:
        await _send_summary(bot_token=bot_token, chat_id=chat_id, user_id=user_id)
        return

    if normalized in {BOT_COMMAND_CANCEL, "cancel"}:
        await _clear_session(chat_id=chat_id)
        await send_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text="Flow cancelled.",
            reply_markup=_quick_keyboard(),
        )
        return

    if normalized in {BOT_COMMAND_ADD, "add transaction"}:
        await _begin_flow(bot_token=bot_token, chat_id=chat_id, user_id=user_id)
        return

    session = await _load_session(chat_id=chat_id)
    if not session:
        quick = await _try_quick_transaction_detect(user_id, raw)
        if quick:
            await _ask_confirm(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=quick)
            return
        await _send_help(bot_token=bot_token, chat_id=chat_id)
        return

    step = str(session.get("step") or "")
    data: dict[str, Any] = dict(session.get("data") or {})
    options: list[dict] = list(session.get("options") or [])

    if step == "type":
        tx_type = _resolve_option(raw, options)
        if not tx_type:
            await _send_text(bot_token=bot_token, chat_id=chat_id, text="Select a valid type.", options=[o["label"] for o in options])
            return
        data["tx_type"] = tx_type
        await _ask_category(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        return

    if step == "category":
        category_code = _resolve_option(raw, options)
        if not category_code:
            await _send_text(bot_token=bot_token, chat_id=chat_id, text="Select a valid category.", options=[o["label"] for o in options])
            return
        selected = next((o for o in options if str(o.get("value")) == category_code), None) or {}
        data["category_code"] = category_code
        data["category_name"] = str(selected.get("label") or category_code)
        await _ask_subcategory(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        return

    if step == "subcategory":
        sub_code = _resolve_option(raw, options)
        if not sub_code:
            await _send_text(bot_token=bot_token, chat_id=chat_id, text="Select a valid subcategory.", options=[o["label"] for o in options])
            return
        selected = next((o for o in options if str(o.get("value")) == sub_code), None) or {}
        data["subcategory_code"] = sub_code
        data["subcategory_name"] = str(selected.get("label") or sub_code)
        await _ask_account(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        return

    if step == "account":
        account_id = _resolve_option(raw, options)
        if not account_id:
            await _send_text(bot_token=bot_token, chat_id=chat_id, text="Select a valid account.", options=[o["label"] for o in options])
            return
        selected = next((o for o in options if str(o.get("value")) == account_id), None) or {}
        data["account_id"] = account_id
        data["account_name"] = str(selected.get("label") or account_id)
        if data.get("tx_type") == "transfer":
            await _ask_target_account(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
            return
        await _ask_mode(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        return

    if step == "target_account":
        target_id = _resolve_option(raw, options)
        if not target_id:
            await _send_text(bot_token=bot_token, chat_id=chat_id, text="Select a valid target account.", options=[o["label"] for o in options])
            return
        selected = next((o for o in options if str(o.get("value")) == target_id), None) or {}
        data["target_account_id"] = target_id
        data["target_account_name"] = str(selected.get("label") or target_id)
        await _ask_mode(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        return

    if step == "mode":
        mode = _resolve_option(raw, options)
        if not mode:
            await _send_text(bot_token=bot_token, chat_id=chat_id, text="Select a valid mode.", options=[o["label"] for o in options])
            return
        data["mode"] = mode
        await _ask_amount(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        return

    if step == "amount":
        amount = _to_float(raw)
        if not amount:
            await _send_text(bot_token=bot_token, chat_id=chat_id, text="Enter a valid positive amount (example: 1200.50).")
            return
        data["amount"] = amount
        await _ask_description(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        return

    if step == "description":
        data["description"] = "" if normalized == "skip" else raw
        await _ask_confirm(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        return

    if step == "confirm":
        choice = _resolve_option(raw, options) or normalized
        if choice in {"cancel", BOT_COMMAND_CANCEL}:
            await _clear_session(chat_id=chat_id)
            await send_message(bot_token=bot_token, chat_id=chat_id, text="Flow cancelled.", reply_markup=_quick_keyboard())
            return
        if choice != "confirm":
            await _send_text(bot_token=bot_token, chat_id=chat_id, text="Choose Confirm or Cancel.", options=["Confirm", "Cancel"])
            return
        try:
            await _finalize_transaction(bot_token=bot_token, chat_id=chat_id, user_id=user_id, data=data)
        except Exception as exc:
            await send_message(
                bot_token=bot_token,
                chat_id=chat_id,
                text=f"Failed to create transaction: {exc}",
                reply_markup=_quick_keyboard(),
            )
            await _clear_session(chat_id=chat_id)
        return

    await _clear_session(chat_id=chat_id)
    await _send_help(bot_token=bot_token, chat_id=chat_id)
