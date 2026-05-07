"""
Transaction inbox service.

Responsibilities:
- Parse statement uploads into normalized inbox rows
- Suggest categories from past transactions
- Prevent duplicate imports via fingerprint checks
- Approve inbox rows by routing through create_transaction()

This module must NOT insert directly into db.transactions.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from xml.etree import ElementTree as ET

from bson import ObjectId
from fastapi import UploadFile

from app.core.errors import NotFoundError, ValidationError
from app.db.mongo import db
from app.helpers.money import round_money
from app.services.transactions import create_transaction

UTC = timezone.utc
XML_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}
DATE_KEYS = {
    "date", "txn date", "transaction date", "posted date", "value date", "time"
}
DESCRIPTION_KEYS = {
    "description", "narration", "remarks", "particulars", "details", "transaction details", "note"
}
DEBIT_KEYS = {"debit", "withdrawal", "debit amount", "dr", "paid out"}
CREDIT_KEYS = {"credit", "deposit", "credit amount", "cr", "paid in"}
AMOUNT_KEYS = {"amount", "txn amount", "transaction amount", "value", "sum"}
TYPE_KEYS = {"type", "dr/cr", "transaction type", "nature"}
MODE_HINTS = {
    "upi": ("upi", "gpay", "google pay", "phonepe", "paytm", "bhim", "vpa"),
    "card": ("card", "pos", "visa", "mastercard", "rupay", "amex"),
    "neft": ("neft",),
    "imps": ("imps",),
    "online": ("online", "netbanking", "internet banking"),
}
DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%m/%d/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y/%m/%d",
)
UNCLEAR_DESCRIPTION_WORDS = {
    "transaction", "debit", "credit", "withdrawal", "deposit", "payment", "transfer"
}
DATE_STYLE_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 30, 36, 45, 46, 47, 50, 57}


def _user_oid(user_id: str) -> ObjectId:
    if not ObjectId.is_valid(user_id):
        raise ValidationError("Invalid user")
    return ObjectId(user_id)


def _row_oid(row_id: str) -> ObjectId:
    if not ObjectId.is_valid(row_id):
        raise ValidationError("Invalid inbox row")
    return ObjectId(row_id)


def _account_oid(account_id: str) -> ObjectId:
    if not ObjectId.is_valid(account_id):
        raise ValidationError("Invalid account")
    return ObjectId(account_id)


def _normalize_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _tokenize_description(value: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{3,}", value.lower())
    return [word for word in words if word not in {"txn", "bank", "stmt", "ref", "utr"}]


def generate_fingerprint(tx_date: date, amount: float, description: str) -> str:
    tail = _normalize_text(description).lower()[-6:]
    payload = f"{tx_date.isoformat()}|{round_money(amount):.2f}|{tail}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def detect_mode(description: str) -> str:
    text = description.lower()
    for mode, hints in MODE_HINTS.items():
        if any(hint in text for hint in hints):
            return mode
    return "unknown"


def is_unclear_description(description: str) -> bool:
    normalized = _normalize_text(description)
    if len(normalized) < 5:
        return True
    tokens = _tokenize_description(normalized)
    if not tokens:
        return True
    return all(token in UNCLEAR_DESCRIPTION_WORDS for token in tokens)


def _parse_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
        return round_money(abs(amount))

    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    text = text.replace("₹", "")
    text = text.replace("rs.", "", 1).replace("rs", "", 1)
    text = text.strip("() ")
    if not text:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    return round_money(abs(amount))


def _excel_serial_to_date(value: float) -> date:
    base = datetime(1899, 12, 30, tzinfo=UTC)
    return (base + timedelta(days=float(value))).date()


def _parse_date_value(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 1 <= float(value) <= 80000:
        return _excel_serial_to_date(float(value))

    text = _normalize_text(value)
    if not text:
        return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    cleaned = text.replace(".", "/").replace("-", "/")
    parts = cleaned.split("/")
    if len(parts) == 3:
        try:
            first = int(parts[0])
            second = int(parts[1])
            third = int(parts[2])
            year = 2000 + third if third < 100 else third
            if first > 12:
                return date(year, second, first)
            return date(year, first, second)
        except ValueError:
            return None
    return None


def _combine_statement_date(value: date) -> datetime:
    return datetime.combine(value, time(hour=12, tzinfo=UTC))


def _worksheet_strings(root: ET.Element) -> dict[int, str]:
    out: dict[int, str] = {}
    if root is None:
        return out
    for idx, si in enumerate(root.findall(".//a:si", XML_NS)):
        pieces = [node.text or "" for node in si.findall(".//a:t", XML_NS)]
        out[idx] = "".join(pieces)
    return out


def _xlsx_date_styles(zf: zipfile.ZipFile) -> set[int]:
    try:
        raw = zf.read("xl/styles.xml")
    except KeyError:
        return set()

    root = ET.fromstring(raw)
    custom_ids: set[int] = set()
    numfmts = root.find("a:numFmts", XML_NS)
    if numfmts is not None:
        for fmt in numfmts.findall("a:numFmt", XML_NS):
            fmt_id = int(fmt.attrib.get("numFmtId", "0"))
            format_code = (fmt.attrib.get("formatCode") or "").lower()
            if any(token in format_code for token in ("yy", "dd", "mm", "mmm", "yyyy")):
                custom_ids.add(fmt_id)

    styles: set[int] = set()
    cell_xfs = root.find("a:cellXfs", XML_NS)
    if cell_xfs is None:
        return styles

    for idx, xf in enumerate(cell_xfs.findall("a:xf", XML_NS)):
        fmt_id = int(xf.attrib.get("numFmtId", "0"))
        if fmt_id in DATE_STYLE_IDS or fmt_id in custom_ids:
            styles.add(idx)
    return styles


def _read_xlsx_rows(content: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        shared_strings: dict[int, str] = {}
        if "xl/sharedStrings.xml" in zf.namelist():
            shared_strings = _worksheet_strings(ET.fromstring(zf.read("xl/sharedStrings.xml")))

        sheet_names = sorted(
            name for name in zf.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not sheet_names:
            return []

        date_styles = _xlsx_date_styles(zf)
        root = ET.fromstring(zf.read(sheet_names[0]))
        rows: list[list[Any]] = []
        for row in root.findall(".//a:sheetData/a:row", XML_NS):
            values: list[Any] = []
            for cell in row.findall("a:c", XML_NS):
                cell_type = cell.attrib.get("t")
                style_idx = int(cell.attrib.get("s", "0"))
                text_node = cell.find("a:v", XML_NS)
                inline_node = cell.find("a:is/a:t", XML_NS)
                raw = text_node.text if text_node is not None else (inline_node.text if inline_node is not None else "")
                if cell_type == "s" and raw != "":
                    values.append(shared_strings.get(int(raw), ""))
                elif cell_type == "inlineStr":
                    values.append(raw or "")
                elif raw == "":
                    values.append("")
                else:
                    if style_idx in date_styles:
                        try:
                            values.append(_excel_serial_to_date(float(raw)))
                            continue
                        except ValueError:
                            pass
                    try:
                        numeric = float(raw)
                        values.append(int(numeric) if numeric.is_integer() else numeric)
                    except ValueError:
                        values.append(raw)
            rows.append(values)

    if not rows:
        return []

    headers = [_normalize_header(cell) or f"column_{idx}" for idx, cell in enumerate(rows[0])]
    return [
        {headers[idx]: row[idx] if idx < len(row) else "" for idx in range(len(headers))}
        for row in rows[1:]
        if any(_normalize_text(value) for value in row)
    ]


def _read_csv_rows(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError("Statement file must include a header row")
    rows: list[dict[str, Any]] = []
    for row in reader:
        rows.append({_normalize_header(key): value for key, value in row.items() if key is not None})
    return rows


def _read_pdf_rows(content: bytes) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - dependency guard
        raise ValidationError("PDF statement import requires the optional 'pypdf' package") from exc

    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+"
        r"(?P<description>.+?)\s+"
        r"(?P<amount>[+-]?\d[\d,]*\.?\d{0,2})\s*"
        r"(?P<kind>CR|DR)?$",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        cleaned = _normalize_text(line)
        if not cleaned:
            continue
        match = pattern.search(cleaned)
        if not match:
            continue
        rows.append(
            {
                "date": match.group("date"),
                "description": match.group("description"),
                "amount": match.group("amount"),
                "type": match.group("kind") or "",
            }
        )
    return rows


async def parse_statement_file(upload: UploadFile) -> list[dict[str, Any]]:
    filename = (upload.filename or "").lower()
    content = await upload.read()
    if not content:
        raise ValidationError("Uploaded statement is empty")

    if filename.endswith(".csv"):
        return _read_csv_rows(content)
    if filename.endswith(".xlsx"):
        return _read_xlsx_rows(content)
    if filename.endswith(".pdf"):
        return _read_pdf_rows(content)
    raise ValidationError("Unsupported file type. Use PDF, CSV, or XLSX")


def _pick_value(row: dict[str, Any], candidates: set[str]) -> Any:
    for key, value in row.items():
        if _normalize_header(key) in candidates and _normalize_text(value) != "":
            return value
    return None


def _infer_type(row: dict[str, Any], amount: float | None) -> tuple[str | None, float | None]:
    debit_value = _pick_value(row, DEBIT_KEYS)
    credit_value = _pick_value(row, CREDIT_KEYS)

    if debit_value not in (None, ""):
        parsed = _parse_amount(debit_value)
        return ("debit", parsed if parsed is not None else amount)
    if credit_value not in (None, ""):
        parsed = _parse_amount(credit_value)
        return ("credit", parsed if parsed is not None else amount)

    raw_type = _normalize_text(_pick_value(row, TYPE_KEYS) or "").lower()
    if raw_type in {"dr", "debit", "withdrawal"}:
        return ("debit", amount)
    if raw_type in {"cr", "credit", "deposit"}:
        return ("credit", amount)
    return (None, amount)


def normalize_statement_row(row: dict[str, Any]) -> dict[str, Any] | None:
    statement_date = _parse_date_value(_pick_value(row, DATE_KEYS))
    description = _normalize_text(_pick_value(row, DESCRIPTION_KEYS) or "")
    amount = _parse_amount(_pick_value(row, AMOUNT_KEYS))
    tx_type, amount = _infer_type(row, amount)

    if statement_date is None or amount is None or not description or tx_type not in {"debit", "credit"}:
        return None

    return {
        "date": statement_date,
        "amount": amount,
        "type": tx_type,
        "description": description,
        "mode": detect_mode(description),
        "raw_data": row,
    }


async def _suggest_category(
    *,
    user_oid: ObjectId,
    tx_type: str,
    description: str,
) -> dict[str, str] | None:
    tokens = _tokenize_description(description)
    if not tokens:
        return None

    or_filters = [{"description": {"$regex": re.escape(token), "$options": "i"}} for token in tokens[:6]]
    cursor = db.transactions.find(
        {
            "user_id": user_oid,
            "type": tx_type,
            "deleted_at": None,
            "is_failed": {"$ne": True},
            "category.code": {"$exists": True},
            "subcategory.code": {"$exists": True},
            "$or": or_filters,
        },
        {
            "description": 1,
            "category": 1,
            "subcategory": 1,
            "created_at": 1,
        },
    ).sort("created_at", -1).limit(120)

    best: dict[str, str] | None = None
    best_score = 0
    async for tx in cursor:
        candidate_tokens = set(_tokenize_description(tx.get("description", "")))
        score = sum(1 for token in tokens if token in candidate_tokens)
        if score <= 0:
            continue
        if score > best_score:
            category = tx.get("category") or {}
            subcategory = tx.get("subcategory") or {}
            if category.get("code") and subcategory.get("code"):
                best = {
                    "category_code": str(category["code"]),
                    "category_name": str(category.get("name") or category["code"]),
                    "subcategory_code": str(subcategory["code"]),
                    "subcategory_name": str(subcategory.get("name") or subcategory["code"]),
                }
                best_score = score
    return best


async def _default_subcategory(category_code: str, tx_type: str) -> dict[str, str]:
    category_doc = await db.categories.find_one(
        {
            "code": category_code,
            "type": tx_type,
            "is_system": True,
        },
        {
            "_id": 0,
            "code": 1,
            "name": 1,
            "subcategories": 1,
        },
    )
    if not category_doc:
        raise ValidationError("Invalid category")

    subcategories = list(category_doc.get("subcategories") or [])
    if not subcategories:
        raise ValidationError("Selected category has no subcategories")

    first = subcategories[0]
    return {
        "category_code": str(category_doc["code"]),
        "category_name": str(category_doc.get("name") or category_doc["code"]),
        "subcategory_code": str(first.get("code") or ""),
        "subcategory_name": str(first.get("name") or first.get("code") or ""),
    }


async def _existing_transaction_fingerprints(
    *,
    user_oid: ObjectId,
    dates: list[date],
) -> set[str]:
    if not dates:
        return set()
    start = _combine_statement_date(min(dates)) - timedelta(days=1)
    end = _combine_statement_date(max(dates)) + timedelta(days=1)
    cursor = db.transactions.find(
        {
            "user_id": user_oid,
            "deleted_at": None,
            "created_at": {"$gte": start, "$lte": end},
            "is_failed": {"$ne": True},
            "type": {"$in": ["debit", "credit"]},
        },
        {
            "created_at": 1,
            "amount": 1,
            "description": 1,
        },
    )

    fingerprints: set[str] = set()
    async for tx in cursor:
        created_at = tx.get("created_at")
        tx_date = created_at.date() if isinstance(created_at, datetime) else _parse_date_value(created_at)
        amount = _parse_amount(tx.get("amount"))
        description = _normalize_text(tx.get("description") or "")
        if tx_date and amount is not None and description:
            fingerprints.add(generate_fingerprint(tx_date, amount, description))
    return fingerprints


async def _existing_inbox_fingerprints(*, user_oid: ObjectId) -> set[str]:
    cursor = db.transaction_inbox.find(
        {
            "user_id": user_oid,
            "status": {"$in": ["pending", "approved"]},
        },
        {"fingerprint": 1},
    )
    return {str(doc.get("fingerprint")) async for doc in cursor if doc.get("fingerprint")}


async def import_statement_to_inbox(
    *,
    user_id: str,
    account_id: str,
    upload: UploadFile,
) -> dict[str, int]:
    user_oid = _user_oid(user_id)
    account_oid = _account_oid(account_id)

    account = await db.accounts.find_one({"_id": account_oid, "user_id": user_oid, "deleted_at": None}, {"_id": 1})
    if not account:
        raise NotFoundError("Account not found")

    raw_rows = await parse_statement_file(upload)
    normalized_rows = [row for row in (normalize_statement_row(raw) for raw in raw_rows) if row]
    if not normalized_rows:
        raise ValidationError("No transactions could be extracted from this statement")

    dates = [row["date"] for row in normalized_rows]
    existing_fingerprints = await _existing_transaction_fingerprints(user_oid=user_oid, dates=dates)
    existing_fingerprints.update(await _existing_inbox_fingerprints(user_oid=user_oid))

    inserted_docs: list[dict[str, Any]] = []
    seen_batch: set[str] = set()
    duplicates = 0
    attention_count = 0

    for row in normalized_rows:
        fingerprint = generate_fingerprint(row["date"], row["amount"], row["description"])
        if fingerprint in existing_fingerprints or fingerprint in seen_batch:
            duplicates += 1
            continue

        suggestion = await _suggest_category(
            user_oid=user_oid,
            tx_type=row["type"],
            description=row["description"],
        )
        needs_attention = suggestion is None or is_unclear_description(row["description"])
        if needs_attention:
            attention_count += 1

        inserted_docs.append(
            {
                "user_id": user_oid,
                "source": "statement",
                "account_id": account_oid,
                "date": _combine_statement_date(row["date"]),
                "amount": row["amount"],
                "type": row["type"],
                "description": row["description"],
                "mode": row["mode"],
                "category": suggestion["category_name"] if suggestion else None,
                "category_code": suggestion["category_code"] if suggestion else None,
                "subcategory_code": suggestion["subcategory_code"] if suggestion else None,
                "subcategory_name": suggestion["subcategory_name"] if suggestion else None,
                "fingerprint": fingerprint,
                "needs_attention": needs_attention,
                "status": "pending",
                "raw_data": row["raw_data"],
                "created_at": datetime.now(UTC),
            }
        )
        seen_batch.add(fingerprint)

    if inserted_docs:
        await db.transaction_inbox.insert_many(inserted_docs)

    return {
        "inserted_count": len(inserted_docs),
        "duplicate_count": duplicates,
        "needs_attention_count": attention_count,
        "parsed_count": len(normalized_rows),
    }


def _serialize_inbox_row(row: dict[str, Any], account_name: str | None = None) -> dict[str, Any]:
    row_date = row.get("date")
    return {
        "id": str(row["_id"]),
        "source": row.get("source", "statement"),
        "account_id": str(row.get("account_id") or ""),
        "account_name": account_name or "",
        "date": row_date.isoformat() if isinstance(row_date, datetime) else "",
        "amount": float(row.get("amount") or 0),
        "type": row.get("type") or "debit",
        "description": row.get("description") or "",
        "mode": row.get("mode") or "unknown",
        "category": row.get("category"),
        "category_code": row.get("category_code"),
        "subcategory_code": row.get("subcategory_code"),
        "subcategory_name": row.get("subcategory_name"),
        "needs_attention": bool(row.get("needs_attention")),
        "status": row.get("status", "pending"),
    }


async def list_inbox_rows(
    *,
    user_id: str,
    only_attention: bool = False,
) -> dict[str, Any]:
    user_oid = _user_oid(user_id)
    query: dict[str, Any] = {
        "user_id": user_oid,
        "status": "pending",
    }
    if only_attention:
        query["needs_attention"] = True

    accounts_cursor = db.accounts.find({"user_id": user_oid, "deleted_at": None}, {"name": 1})
    account_map = {str(acc["_id"]): acc.get("name", "Account") async for acc in accounts_cursor}

    cursor = db.transaction_inbox.find(query).sort([("needs_attention", -1), ("date", -1), ("created_at", -1)])
    rows: list[dict[str, Any]] = []
    attention_count = 0
    type_counts: Counter[str] = Counter()
    async for row in cursor:
        rows.append(_serialize_inbox_row(row, account_map.get(str(row.get("account_id") or ""), "Account")))
        if row.get("needs_attention"):
            attention_count += 1
        type_counts[str(row.get("source") or "statement")] += 1

    return {
        "rows": rows,
        "summary": {
            "pending_count": len(rows),
            "needs_attention_count": attention_count,
            "statement_count": type_counts.get("statement", 0),
            "sms_count": type_counts.get("sms", 0),
        },
    }


async def update_inbox_row(
    *,
    user_id: str,
    row_id: str,
    amount: float | None = None,
    description: str | None = None,
    tx_type: str | None = None,
    mode: str | None = None,
    category_code: str | None = None,
    statement_date: str | None = None,
) -> dict[str, Any]:
    user_oid = _user_oid(user_id)
    oid = _row_oid(row_id)
    row = await db.transaction_inbox.find_one(
        {"_id": oid, "user_id": user_oid, "status": "pending"},
    )
    if not row:
        raise NotFoundError("Inbox row not found")

    update: dict[str, Any] = {}
    next_type = tx_type or str(row.get("type") or "debit")
    next_description = _normalize_text(description if description is not None else row.get("description") or "")
    next_amount = round_money(float(amount)) if amount is not None else float(row.get("amount") or 0)
    if next_amount <= 0:
        raise ValidationError("Amount must be positive")
    if next_type not in {"debit", "credit"}:
        raise ValidationError("Type must be debit or credit")

    if description is not None:
        if not next_description:
            raise ValidationError("Description is required")
        update["description"] = next_description
        if mode is None:
            update["mode"] = detect_mode(next_description)

    if amount is not None:
        update["amount"] = next_amount
    if tx_type is not None:
        update["type"] = next_type
        if category_code is None:
            update["category"] = None
            update["category_code"] = None
            update["subcategory_code"] = None
            update["subcategory_name"] = None
    if mode is not None:
        if mode not in {"upi", "card", "neft", "imps", "online", "unknown"}:
            raise ValidationError("Invalid mode")
        update["mode"] = mode

    next_date = row.get("date")
    if statement_date is not None:
        parsed = _parse_date_value(statement_date)
        if not parsed:
            raise ValidationError("Invalid date")
        next_date = _combine_statement_date(parsed)
        update["date"] = next_date

    if category_code is not None:
        if category_code.strip():
            default_meta = await _default_subcategory(category_code.strip(), next_type)
            update["category"] = default_meta["category_name"]
            update["category_code"] = default_meta["category_code"]
            update["subcategory_code"] = default_meta["subcategory_code"]
            update["subcategory_name"] = default_meta["subcategory_name"]
        else:
            update["category"] = None
            update["category_code"] = None
            update["subcategory_code"] = None
            update["subcategory_name"] = None

    next_category = update.get("category", row.get("category"))
    if not next_description:
        raise ValidationError("Description is required")

    next_row_date = next_date.date() if isinstance(next_date, datetime) else _parse_date_value(next_date)
    if not next_row_date:
        raise ValidationError("Row date is required")

    next_fingerprint = generate_fingerprint(next_row_date, next_amount, next_description)
    duplicate_inbox = await db.transaction_inbox.find_one(
        {
            "_id": {"$ne": oid},
            "user_id": user_oid,
            "fingerprint": next_fingerprint,
            "status": {"$in": ["pending", "approved"]},
        },
        {"_id": 1},
    )
    if duplicate_inbox:
        raise ValidationError("This row matches an existing inbox item")

    tx_fingerprints = await _existing_transaction_fingerprints(
        user_oid=user_oid,
        dates=[next_row_date],
    )
    if next_fingerprint in tx_fingerprints:
        raise ValidationError("This row matches an existing transaction")

    update["fingerprint"] = next_fingerprint
    update["needs_attention"] = (not next_category) or is_unclear_description(next_description)

    await db.transaction_inbox.update_one({"_id": oid}, {"$set": update})
    updated = await db.transaction_inbox.find_one({"_id": oid})
    return _serialize_inbox_row(updated)


async def approve_inbox_rows(
    *,
    user_id: str,
    row_ids: list[str],
    request=None,
) -> dict[str, Any]:
    user_oid = _user_oid(user_id)
    valid_ids = [_row_oid(row_id) for row_id in row_ids]
    if not valid_ids:
        raise ValidationError("Select at least one inbox row")

    approved = 0
    failed: list[dict[str, str]] = []
    cursor = db.transaction_inbox.find(
        {
            "_id": {"$in": valid_ids},
            "user_id": user_oid,
            "status": "pending",
        }
    )
    async for row in cursor:
        if not row.get("category_code") or not row.get("subcategory_code"):
            failed.append({"id": str(row["_id"]), "error": "Category is required before approval"})
            continue
        row_date = row.get("date")
        row_day = row_date.date() if isinstance(row_date, datetime) else _parse_date_value(row_date)
        if not row_day:
            failed.append({"id": str(row["_id"]), "error": "Transaction date is missing"})
            continue
        tx_fingerprints = await _existing_transaction_fingerprints(user_oid=user_oid, dates=[row_day])
        if str(row.get("fingerprint") or "") in tx_fingerprints:
            await db.transaction_inbox.update_one(
                {"_id": row["_id"]},
                {"$set": {"status": "discarded", "discarded_at": datetime.now(UTC)}},
            )
            failed.append({"id": str(row["_id"]), "error": "Skipped because the transaction already exists"})
            continue
        try:
            await create_transaction(
                user_id=user_id,
                account_id=str(row["account_id"]),
                amount=float(row["amount"]),
                tx_type=str(row["type"]),
                mode=str(row.get("mode") or "unknown"),
                category_code=str(row["category_code"]),
                subcategory_code=str(row["subcategory_code"]),
                description=str(row.get("description") or ""),
                transaction_date=row_date,
                request=request,
            )
            await db.transaction_inbox.update_one(
                {"_id": row["_id"]},
                {"$set": {"status": "approved", "approved_at": datetime.now(UTC)}},
            )
            approved += 1
        except Exception as exc:
            failed.append({"id": str(row["_id"]), "error": str(exc)})

    return {
        "approved_count": approved,
        "failed": failed,
    }


async def discard_inbox_rows(*, user_id: str, row_ids: list[str]) -> dict[str, Any]:
    user_oid = _user_oid(user_id)
    valid_ids = [_row_oid(row_id) for row_id in row_ids]
    if not valid_ids:
        raise ValidationError("Select at least one inbox row")

    result = await db.transaction_inbox.update_many(
        {
            "_id": {"$in": valid_ids},
            "user_id": user_oid,
            "status": "pending",
        },
        {"$set": {"status": "discarded", "discarded_at": datetime.now(UTC)}},
    )
    return {"discarded_count": int(result.modified_count)}
