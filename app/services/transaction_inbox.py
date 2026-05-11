"""
Transaction Inbox Service - Complete Redesign

ARCHITECTURE (Three-Stage Pipeline):
1. PARSE STAGE: Extract raw rows from statement files (PDF/CSV/XLSX)
   - No normalization, no deduplication, just extract what's in the file
   - Return list of parsed rows with raw data

2. NORMALIZE STAGE: Clean and auto-detect fields
   - Standardize dates, amounts, descriptions
   - Auto-detect type (debit/credit), mode (upi/card/transfer)
   - Auto-detect category from merchant memory
   - Compute confidence score
   - NO deduplication here - that's the next stage

3. BUFFER INSERT STAGE: Check duplicates and insert to buffer table
   - Check date+amount against existing transactions
   - Check date+amount against existing inbox
   - Insert only new transactions to buffer
   - Report detailed metrics (parsed, normalized, duplicates, inserted)

RESPONSIBILITIES:
- Import statements (PDF/CSV/XLSX) → buffer table
- Parse SMS → buffer table
- Clear buffer on approval
- Suggest categories from merchant memory + history
- Provide observable metrics and error reports
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from xml.etree import ElementTree as ET

from bson import ObjectId
from fastapi import UploadFile
from pymongo.errors import BulkWriteError

from app.core.errors import NotFoundError, ValidationError
from app.db.mongo import db
from app.helpers.money import round_money
from app.services.categories import get_subcategories
from app.services.transactions import create_transaction

UTC = timezone.utc

XML_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Column name patterns for detecting fields in statements
DATE_KEYS = {
    "date", "txn date", "transaction date", "posted date", "value date",
    "booking date", "time", "statement date", "tx date", "tran date"
}
DESCRIPTION_KEYS = {
    "description", "narration", "remarks", "particulars", "details",
    "transaction details", "merchant", "note", "reference", "trans desc"
}
DEBIT_KEYS = {"debit", "withdrawal", "debit amount", "dr", "paid out", "debited"}
CREDIT_KEYS = {"credit", "deposit", "credit amount", "cr", "paid in", "credited"}
AMOUNT_KEYS = {"amount", "txn amount", "transaction amount", "value", "sum", "trans amount"}
TYPE_KEYS = {"type", "dr/cr", "transaction type", "nature", "tx type"}

DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y",
    "%d %b %Y", "%d %B %Y", "%Y/%m/%d", "%d-%b-%Y", "%d-%B-%Y",
)
DATE_STYLE_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 30, 36, 45, 46, 47, 50, 57}

# Regex patterns for extracting data
DATE_TOKEN_RE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{2,4})\b"
)
AMOUNT_RE = re.compile(r"[+-]?\d[\d,]*\.?\d{0,2}")
AMOUNT_WITH_MARKER_RE = re.compile(r"([+-]?\d[\d,]*\.?\d{0,2})\s*(CR|DR)\b", re.IGNORECASE)

DESC_NOISE_RE = re.compile(
    r"\b(?:ref(?:erence)?|rrn|utr|txn|txnid|trace|id|no|number|a/c|acct|ifsc|upi ref|imps ref)\b[:#-]*\s*[A-Za-z0-9\-_/]{4,}",
    flags=re.IGNORECASE,
)
DESC_DIGIT_CLUSTER_RE = re.compile(r"\b\d{6,}\b")
DESC_SPACES_RE = re.compile(r"\s+")

SMS_AMOUNT_RE = re.compile(
    r"(?:INR|Rs\.?|₹)\s*([+-]?\d[\d,]*\.?\d{0,2})|([+-]?\d[\d,]*\.?\d{0,2})\s*(?:INR|Rs\.?|₹)",
    flags=re.IGNORECASE,
)

TXN_MARKER_RE = re.compile(r"(UPI/|BIL/|ATM|POS|NEFT|IMPS|NACH|ACH|INB|TRF/|MB/)", re.IGNORECASE)
PDF_FOOTER_RE = re.compile(
    r"(?:account related other information|sincerely|team icici bank|code of commitment|grievance redressal|corporate office)",
    re.IGNORECASE,
)

MODE_MAP = {
    "upi": ["upi"],
    "card": ["pos", "card", "atm"],
    "transfer": ["neft", "imps"],
}

CATEGORY_STOPWORDS = {
    "payment", "paid", "received", "debit", "credit", "transfer",
    "purchase", "txn", "bank", "account", "statement", "upi",
    "pos", "imps", "neft", "inr", "salary",
}


# =========================================================================
# HELPERS
# =========================================================================

def _user_oid(user_id: str) -> ObjectId:
    if not ObjectId.is_valid(user_id):
        raise ValidationError("Invalid user")
    return ObjectId(user_id)


def _account_oid(account_id: str) -> ObjectId:
    if not ObjectId.is_valid(account_id):
        raise ValidationError("Invalid account")
    return ObjectId(account_id)


def _row_oid(row_id: str) -> ObjectId:
    if not ObjectId.is_valid(row_id):
        raise ValidationError("Invalid inbox row")
    return ObjectId(row_id)


def _normalize_header(value: Any) -> str:
    """Normalize column header for comparison"""
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _normalize_text(value: Any) -> str:
    """Normalize text value by collapsing whitespace"""
    return re.sub(r"\s+", " ", str(value or "").strip())


def _excel_serial_to_date(value: float) -> date:
    """Convert Excel serial date to Python date"""
    base = datetime(1899, 12, 30, tzinfo=UTC)
    return (base + timedelta(days=float(value))).date()


def _parse_date_value(value: Any) -> date | None:
    """Parse date from various formats"""
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

    # Fallback: try to parse with flexible separator handling
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
    """Convert date to datetime at noon UTC"""
    return datetime.combine(value, time(hour=12, tzinfo=UTC))


def _parse_amount(value: Any) -> float | None:
    """Parse amount from various formats"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round_money(abs(float(value)))

    text = str(value).strip()
    if not text:
        return None

    text = text.replace(",", "").replace("₹", "")
    text = text.replace("INR", "").replace("inr", "")
    text = text.replace("rs.", "").replace("Rs.", "")
    text = text.replace("rs", "").replace("Rs", "")
    text = text.strip("() ")

    if not text:
        return None

    try:
        return round_money(abs(float(text)))
    except ValueError:
        return None


def clean_description(value: str) -> str:
    """Clean description by removing noise and standardizing format"""
    text = _normalize_text(value)
    if not text:
        return ""

    # Remove reference numbers, UTRs, etc.
    text = DESC_NOISE_RE.sub(" ", text)
    text = DATE_TOKEN_RE.sub(" ", text)
    
    # Remove long digit clusters (usually account numbers)
    text = DESC_DIGIT_CLUSTER_RE.sub(" ", text)
    
    # Remove balance information
    text = re.sub(r"\b(?:avl bal|bal(?:ance)?|closing bal|available balance)\b.*$", "", text, flags=re.IGNORECASE)
    
    # Remove special characters except basic ones
    text = re.sub(r"[^A-Za-z0-9&./()'\- ]", " ", text)
    
    # Normalize spaces
    text = DESC_SPACES_RE.sub(" ", text).strip(" -|/")
    
    return text


def extract_merchant_keyword(description: str) -> str | None:
    """Extract main merchant keyword from description"""
    cleaned = clean_description(description)
    if not cleaned:
        return None

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9&.-]{2,}", cleaned)
    for token in tokens:
        low = token.lower()
        if low in CATEGORY_STOPWORDS:
            continue
        return low
    return None


def detect_mode(description: str) -> str:
    """Detect transaction mode (upi/card/transfer)"""
    text = f" {description.lower()} "
    
    if any(f" {k} " in text for k in MODE_MAP["upi"]):
        return "upi"
    if any(f" {k} " in text for k in MODE_MAP["card"]):
        return "card"
    if any(f" {k} " in text for k in MODE_MAP["transfer"]):
        return "transfer"
    return "unknown"


def infer_type_from_description(description: str, explicit_type: str | None = None) -> str:
    """Infer transaction type (debit/credit) from description"""
    if explicit_type:
        low = explicit_type.strip().lower()
        if low in {"credit", "cr"}:
            return "credit"
        if low in {"debit", "dr"}:
            return "debit"

    text = f" {description.lower()} "
    # ICICI Bank: "Payment fr" = "Payment from" = incoming credit
    if " credit " in text or " salary " in text or " credited " in text:
        return "credit"
    if "payment fr" in text or "payment from" in text:
        return "credit"
    if "received" in text or "refund" in text:
        return "credit"
    return "debit"


def generate_fingerprint(tx_date: date, amount: float) -> str:
    """Generate deduplication fingerprint from date + amount"""
    payload = f"{tx_date.isoformat()}|{round_money(amount):.2f}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _compute_confidence(
    *,
    description_match: bool = False,
    category_autofill: bool = False,
    mode_detected: bool = False,
    merchant_memory_hit: bool = False
) -> int:
    """Compute confidence score (0-100) for auto-approval"""
    score = 0
    if description_match:
        score += 40
    if category_autofill:
        score += 30
    if mode_detected:
        score += 20
    if merchant_memory_hit:
        score += 10
    return int(max(0, min(100, score)))


def _pick_value(row: dict[str, Any], candidates: set[str]) -> Any:
    """Find first non-empty value matching one of the candidate field names"""
    for key, value in row.items():
        if _normalize_header(key) in candidates and _normalize_text(value) != "":
            return value
    return None


# =========================================================================
# STAGE 1: PARSE STATEMENT FILE → RAW ROWS
# =========================================================================

def _worksheet_strings(root: ET.Element) -> dict[int, str]:
    """Extract shared strings from XLSX"""
    out: dict[int, str] = {}
    if root is None:
        return out
    for idx, si in enumerate(root.findall(".//a:si", XML_NS)):
        pieces = [node.text or "" for node in si.findall(".//a:t", XML_NS)]
        out[idx] = "".join(pieces)
    return out


def _xlsx_date_styles(zf: zipfile.ZipFile) -> set[int]:
    """Detect date cell styles in XLSX"""
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


def _parse_xlsx_file(content: bytes) -> list[dict[str, Any]]:
    """Parse XLSX statement file"""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        shared_strings: dict[int, str] = {}
        if "xl/sharedStrings.xml" in zf.namelist():
            shared_strings = _worksheet_strings(ET.fromstring(zf.read("xl/sharedStrings.xml")))

        sheet_names = sorted(
            name for name in zf.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
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


def _parse_csv_file(content: bytes) -> list[dict[str, Any]]:
    """Parse CSV statement file"""
    text = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError("CSV file must include a header row")
    
    rows: list[dict[str, Any]] = []
    for row in reader:
        rows.append({_normalize_header(key): value for key, value in row.items() if key is not None})
    return rows


def _parse_pdf_file(content: bytes) -> list[dict[str, Any]]:
    """Parse PDF statement file - Optimized for Indian bank statements.

    Strategy: split each page's full text by ALL date markers found in it.
    This correctly handles:
      - Date-only lines (a date with no transaction on the same line).
      - Multiple date markers within a single extracted-text line.
      - Transaction lines that immediately follow their date without any
        date token of their own.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValidationError("PDF statement import requires the optional 'pypdf' package") from exc

    _SKIP_TOKENS = ("opening balance", "closing balance", "total", "page ", "statement")

    reader = PdfReader(io.BytesIO(content))
    rows: list[dict[str, Any]] = []
    # Track date across pages so dateless lines on a new page still get a date.
    current_date: str | None = None

    for page in reader.pages:
        raw_page = page.extract_text() or ""
        # Collapse newlines to spaces so the entire page is one searchable string.
        # This lets us find all date markers in order, regardless of line wrapping.
        page_text = _normalize_text(raw_page)
        if not page_text:
            continue

        date_matches = list(DATE_TOKEN_RE.finditer(page_text))

        if not date_matches:
            # No date on this page — append any transaction-looking text to last row.
            if current_date and not PDF_FOOTER_RE.search(page_text):
                if TXN_MARKER_RE.search(page_text) or AMOUNT_RE.search(page_text):
                    for candidate in _split_pdf_body_candidates(page_text):
                        rows.append({
                            "raw_line": page_text[:200],
                            "date_text": current_date,
                            "body": candidate,
                        })
            continue

        # Split the page text into date-keyed segments.
        # Each segment is the text between this date marker and the next.
        for i, dm in enumerate(date_matches):
            date_text = dm.group(1)
            current_date = date_text

            seg_start = dm.end()
            seg_end = date_matches[i + 1].start() if i + 1 < len(date_matches) else len(page_text)
            segment = _normalize_text(page_text[seg_start:seg_end])

            if not segment:
                # Date-only marker with no body (e.g. a day-header line).
                # current_date has been updated; next segment will use it.
                continue

            # Drop header/footer noise within the segment.
            low = segment.lower()
            if any(t in low for t in _SKIP_TOKENS):
                continue
            if PDF_FOOTER_RE.search(segment):
                continue

            for candidate in _split_pdf_body_candidates(segment):
                rows.append({
                    "raw_line": page_text[dm.start(): min(dm.start() + 200, seg_end)],
                    "date_text": date_text,
                    "body": candidate,
                })

    return rows


def _truncate_pdf_footer(text: str) -> str:
    """Remove long non-transaction footer/legal text from PDF extraction."""
    if not text:
        return text
    marker = PDF_FOOTER_RE.search(text)
    if not marker:
        return text
    return _normalize_text(text[:marker.start()])


def _split_pdf_body_candidates(body: str) -> list[str]:
    """Split a PDF body that may contain many transactions into row candidates."""
    body = _truncate_pdf_footer(_normalize_text(body))
    if not body:
        return []

    # Keep any opening balance / preface as a standalone candidate when present.
    prefix = ""
    first_marker = TXN_MARKER_RE.search(body)
    if first_marker and first_marker.start() > 0:
        prefix = _normalize_text(body[:first_marker.start()])
        body = _normalize_text(body[first_marker.start():])

    candidates: list[str] = []
    if prefix and AMOUNT_RE.search(prefix):
        candidates.append(prefix)

    starts = list(TXN_MARKER_RE.finditer(body))
    if not starts:
        if AMOUNT_RE.search(body):
            candidates.append(body)
        return candidates

    positions = [m.start() for m in starts]
    positions.append(len(body))
    for i in range(len(positions) - 1):
        seg = _normalize_text(body[positions[i]:positions[i + 1]])
        if not seg:
            continue
        if not AMOUNT_RE.search(seg):
            continue
        candidates.append(seg)

    return candidates


async def parse_statement_file(upload: UploadFile) -> tuple[list[dict[str, Any]], list[str]]:
    """
    STAGE 1: Parse statement file
    
    Returns:
        (raw_rows, errors)
        - raw_rows: List of extracted rows (no normalization)
        - errors: List of parsing errors encountered
    """
    filename = (upload.filename or "").lower()
    content = await upload.read()
    if not content:
        raise ValidationError("Uploaded statement is empty")

    errors: list[str] = []
    raw_rows: list[dict[str, Any]] = []

    try:
        if filename.endswith(".csv"):
            raw_rows = _parse_csv_file(content)
        elif filename.endswith(".xlsx"):
            raw_rows = _parse_xlsx_file(content)
        elif filename.endswith(".pdf"):
            raw_rows = _parse_pdf_file(content)
        else:
            raise ValidationError("Unsupported file type. Use PDF, CSV, or XLSX")
    except Exception as exc:
        errors.append(f"File parsing error: {str(exc)}")

    return raw_rows, errors


# =========================================================================
# STAGE 2: NORMALIZE ROWS → CLEAN, AUTO-DETECT, SCORE
# =========================================================================

def normalize_csv_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a CSV/XLSX row"""
    statement_date = _parse_date_value(_pick_value(row, DATE_KEYS))
    description_raw = _normalize_text(_pick_value(row, DESCRIPTION_KEYS) or "")
    amount = _parse_amount(_pick_value(row, AMOUNT_KEYS))

    # Try to infer type from debit/credit columns
    tx_type = "debit"
    debit_value = _pick_value(row, DEBIT_KEYS)
    credit_value = _pick_value(row, CREDIT_KEYS)
    
    if debit_value not in (None, ""):
        tx_type = "debit"
    elif credit_value not in (None, ""):
        tx_type = "credit"
    else:
        raw_type = _normalize_text(_pick_value(row, TYPE_KEYS) or "")
        tx_type = infer_type_from_description(description_raw, explicit_type=raw_type)

    description = clean_description(description_raw)

    # Validation
    if statement_date is None:
        return None
    if amount is None or amount <= 0:
        return None
    if not description:
        return None
    if tx_type not in {"debit", "credit"}:
        return None

    return {
        "date": statement_date,
        "amount": amount,
        "type": tx_type,
        "description": description,
        "mode": detect_mode(description),
        "raw_data": row,
    }


def normalize_pdf_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a PDF row - Optimized for Indian bank format"""
    date_text = row.get("date_text")
    body = row.get("body", "")

    statement_date = _parse_date_value(date_text) if date_text else None
    if statement_date is None:
        return None

    cleaned_body = _normalize_text(body)
    if not cleaned_body:
        return None
    
    # DEFENSIVE: Remove ANY remaining leading date tokens
    # Some PDF extractions still have date in body despite _parse_pdf_file cleanup
    while True:
        lead = DATE_TOKEN_RE.match(cleaned_body)
        if not lead:
            break
        cleaned_body = _normalize_text(cleaned_body[lead.end():])
    
    if not cleaned_body:
        return None

    # Try to extract amount with CR/DR marker first
    marker_matches = list(AMOUNT_WITH_MARKER_RE.finditer(cleaned_body))
    amount_value: float | None = None
    tx_type: str | None = None
    description = cleaned_body

    if marker_matches:
        # Use last marker match (usually the transaction, not balance)
        marker = marker_matches[-1]
        amount_value = _parse_amount(marker.group(1))
        tx_type = "credit" if marker.group(2).upper() == "CR" else "debit"
        description = _normalize_text(cleaned_body[:marker.start()])
    else:
        # Extract amounts - CRITICAL for Indian format with commas
        amount_matches = list(AMOUNT_RE.finditer(cleaned_body))
        if not amount_matches:
            return None

        # FILTER STRATEGY - prioritize real currency amounts:
        # 1. Remove year values (1900-2100)
        # 2. Remove single/double-digit month/day values
        # 3. Remove very large reference numbers (>10M)
        # 4. STRONGLY prefer amounts with exactly 2 decimals (.XX format)
        
        filtered_matches = []
        for m in amount_matches:
            token = m.group(0).strip()
            raw_token = token.replace("+", "").replace("-", "").strip()
            
            # Skip year-like integers
            if raw_token.isdigit() and 1900 <= int(raw_token) <= 2100:
                continue
            
            # Skip day/month values when not money-formatted
            if raw_token.isdigit() and 1 <= int(raw_token) <= 31 and len(raw_token) <= 2:
                if "," not in token and "." not in token:
                    continue
            
            parsed = _parse_amount(token)
            if parsed is None or parsed <= 0:
                continue
            
            # FILTER OUT: Very large reference numbers (>10 million)
            # Real transactions are typically much smaller
            if parsed > 10000000:
                continue
            
            filtered_matches.append(m)
        
        if not filtered_matches:
            return None

        # PRIORITY 1: Amounts with exactly 2 decimal places (currency format: XXX.XX)
        # Use the FIRST decimal amount: in "desc AMOUNT.xx BALANCE.xx" the first is
        # always the transaction amount. Penultimate fails when bodies have merged transactions.
        decimal_matches = [m for m in filtered_matches if re.search(r'\.\d{2}(?:\D|$)', m.group(0))]
        if decimal_matches:
            if len(decimal_matches) >= 2:
                pick = decimal_matches[0]
            else:
                pick = decimal_matches[-1]
            amount_value = _parse_amount(pick.group(0))
            description = _normalize_text(cleaned_body[:pick.start()])
        else:
            # PRIORITY 2: Indian format amounts with commas
            money_like = [m for m in filtered_matches if "," in m.group(0)]
            if money_like:
                if len(money_like) >= 2:
                    pick = money_like[-2]
                else:
                    pick = money_like[-1]
                amount_value = _parse_amount(pick.group(0))
                description = _normalize_text(cleaned_body[:pick.start()])
            else:
                # FALLBACK: Use standard heuristic
                if len(filtered_matches) >= 3:
                    pick = filtered_matches[-2]  # Prefer second-to-last
                else:
                    pick = filtered_matches[-1]
                amount_value = _parse_amount(pick.group(0))
                description = _normalize_text(cleaned_body[:pick.start()])
        
        tx_type = infer_type_from_description(description)

    # Final cleanup
    description = DATE_TOKEN_RE.sub(" ", description)
    description = _normalize_text(description)

    if amount_value is None or amount_value <= 0:
        return None

    cleaned_desc = clean_description(description)
    if not cleaned_desc or not re.search(r"[A-Za-z]", cleaned_desc):
        return None

    return {
        "date": statement_date,
        "amount": amount_value,
        "type": tx_type or "debit",
        "description": cleaned_desc,
        "mode": detect_mode(cleaned_desc),
        "raw_data": row,
    }


async def normalize_rows(
    raw_rows: list[dict[str, Any]],
    source_format: str = "csv"
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    STAGE 2: Normalize rows
    
    Returns:
        (normalized_rows, normalized_errors)
        - normalized_rows: Successfully normalized rows
        - normalized_errors: List of rows that failed normalization with reasons
    """
    normalized_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, raw_row in enumerate(raw_rows):
        try:
            if source_format == "pdf":
                # Safety net: some PDFs still arrive as merged date-block rows.
                # Split again here so Stage 2 can normalize each transaction candidate.
                body = _normalize_text(raw_row.get("body") if isinstance(raw_row, dict) else "")
                split_bodies = _split_pdf_body_candidates(body) if body else []
                candidate_rows = (
                    [{**raw_row, "body": candidate} for candidate in split_bodies]
                    if split_bodies
                    else [raw_row]
                )

                row_had_success = False
                for sub_idx, candidate_row in enumerate(candidate_rows):
                    normalized = normalize_pdf_row(candidate_row)
                    if normalized:
                        normalized_rows.append(normalized)
                        row_had_success = True
                    else:
                        errors.append({
                            "row_index": idx,
                            "raw_data": str(candidate_row)[:100],
                            "error": "Failed to extract required fields (date, amount, description)"
                        })

                # Reduce noisy duplicate errors when at least one candidate succeeded.
                if row_had_success:
                    continue
            else:
                normalized = normalize_csv_row(raw_row)
                if normalized:
                    normalized_rows.append(normalized)
                else:
                    errors.append({
                        "row_index": idx,
                        "raw_data": str(raw_row)[:100],
                        "error": "Failed to extract required fields (date, amount, description)"
                    })
        except Exception as exc:
            errors.append({
                "row_index": idx,
                "raw_data": str(raw_row)[:100],
                "error": str(exc)
            })

    return normalized_rows, errors


# =========================================================================
# STAGE 3: INSERT TO BUFFER → DEDUPE, SCORE, STORE
# =========================================================================

async def _existing_transaction_fingerprints(user_oid: ObjectId, dates: list[date]) -> set[str]:
    """Get fingerprints of existing transactions for date range"""
    if not dates:
        return set()

    start_dt = _combine_statement_date(min(dates)) - timedelta(days=1)
    end_dt = _combine_statement_date(max(dates)) + timedelta(days=1)

    cursor = db.transactions.find(
        {
            "user_id": user_oid,
            "deleted_at": None,
            "is_failed": {"$ne": True},
            "type": {"$in": ["debit", "credit"]},
            "$or": [
                {"transaction_date": {"$gte": start_dt, "$lte": end_dt}},
                {"created_at": {"$gte": start_dt, "$lte": end_dt}},
            ],
        },
        {"transaction_date": 1, "created_at": 1, "amount": 1},
    )

    fingerprints: set[str] = set()
    async for tx in cursor:
        tx_date_obj = tx.get("transaction_date") or tx.get("created_at")
        tx_date = tx_date_obj.date() if isinstance(tx_date_obj, datetime) else _parse_date_value(tx_date_obj)
        amount = _parse_amount(tx.get("amount"))
        if tx_date and amount is not None:
            fingerprints.add(generate_fingerprint(tx_date, amount))
    return fingerprints


async def _existing_inbox_fingerprints(user_oid: ObjectId, statuses: list[str] | None = None) -> set[str]:
    """Get fingerprints of existing inbox rows"""
    if statuses is None:
        statuses = ["pending", "approved"]

    cursor = db.transaction_inbox.find(
        {"user_id": user_oid, "status": {"$in": statuses}},
        {"fingerprint": 1},
    )
    return {str(doc.get("fingerprint")) async for doc in cursor if doc.get("fingerprint")}


async def _lookup_merchant_memory(
    user_oid: ObjectId,
    merchant_keyword: str | None,
    tx_type: str
) -> dict[str, Any] | None:
    """Lookup category suggestion from merchant memory"""
    if not merchant_keyword:
        return None

    return await db.merchant_memory.find_one(
        {
            "user_id": user_oid,
            "merchant_keyword": merchant_keyword,
            "type": tx_type,
        },
        {"_id": 0, "category_code": 1, "category_name": 1, "subcategory_code": 1, "subcategory_name": 1},
    )


async def _suggest_category_from_history(
    user_oid: ObjectId,
    tx_type: str,
    description: str
) -> tuple[dict[str, str] | None, bool]:
    """Suggest category from transaction history"""
    words = re.findall(r"[a-z0-9]{3,}", description.lower())
    tokens = [word for word in words if len(word) > 2]
    
    if not tokens:
        return (None, False)

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
        {"description": 1, "category": 1, "subcategory": 1, "created_at": 1},
    ).sort("created_at", -1).limit(150)

    best: dict[str, str] | None = None
    best_score = 0

    async for tx in cursor:
        candidate_words = re.findall(r"[a-z0-9]{3,}", str(tx.get("description") or "").lower())
        candidate_tokens = {word for word in candidate_words if len(word) > 2}
        score = sum(1 for token in tokens if token in candidate_tokens)
        
        if score <= 0:
            continue
            
        category = tx.get("category") or {}
        subcategory = tx.get("subcategory") or {}
        
        if score > best_score and category.get("code") and subcategory.get("code"):
            best_score = score
            best = {
                "category_code": str(category["code"]),
                "category_name": str(category.get("name") or category["code"]),
                "subcategory_code": str(subcategory["code"]),
                "subcategory_name": str(subcategory.get("name") or subcategory["code"]),
            }

    return (best, best_score > 0)


async def _upsert_merchant_memory(
    user_oid: ObjectId,
    merchant_keyword: str | None,
    tx_type: str,
    category_code: str,
    category_name: str,
    subcategory_code: str,
    subcategory_name: str,
) -> None:
    """Learn merchant → category mapping"""
    if not merchant_keyword:
        return

    now = datetime.now(UTC)
    await db.merchant_memory.update_one(
        {"user_id": user_oid, "merchant_keyword": merchant_keyword, "type": tx_type},
        {
            "$set": {
                "category_code": category_code,
                "category_name": category_name,
                "subcategory_code": subcategory_code,
                "subcategory_name": subcategory_name,
                "updated_at": now,
                "last_used_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
            "$inc": {"usage_count": 1},
        },
        upsert=True,
    )


async def _insert_rows_to_buffer(
    user_oid: ObjectId,
    account_oid: ObjectId,
    source: str,
    normalized_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    STAGE 3: Insert normalized rows to buffer with deduplication
    
    Returns:
        {
            "inserted_count": N,
            "duplicate_count": N,
            "needs_attention_count": N,
            "statement_total": amount,
            "inbox_total": amount,
            "errors": [...],
        }
    """
    if not normalized_rows:
        return {
            "inserted_count": 0,
            "duplicate_count": 0,
            "needs_attention_count": 0,
            "statement_total": 0.0,
            "inbox_total": 0.0,
            "errors": [],
        }

    # Get existing fingerprints to check for duplicates
    dates = [row["date"] for row in normalized_rows]
    existing_tx_fingerprints = await _existing_transaction_fingerprints(user_oid, dates)
    existing_inbox_fingerprints = await _existing_inbox_fingerprints(user_oid)

    inserted_docs: list[dict[str, Any]] = []
    seen_batch: set[str] = set()
    duplicates = 0
    attention_count = 0
    statement_total = 0.0
    inserted_total = 0.0
    errors: list[dict[str, Any]] = []

    for row in normalized_rows:
        statement_total += float(row["amount"])
        fingerprint = generate_fingerprint(row["date"], row["amount"])

        # Check if duplicate
        if fingerprint in existing_tx_fingerprints or fingerprint in existing_inbox_fingerprints or fingerprint in seen_batch:
            duplicates += 1
            continue

        try:
            # Try to get category suggestion
            merchant_keyword = extract_merchant_keyword(row["description"])
            memory_suggestion = await _lookup_merchant_memory(user_oid, merchant_keyword, row["type"])
            history_suggestion, description_match = await _suggest_category_from_history(
                user_oid, row["type"], row["description"]
            )

            suggestion = memory_suggestion or history_suggestion
            category_autofill = suggestion is not None
            merchant_hit = memory_suggestion is not None
            mode_detected = row["mode"] != "unknown"

            confidence = _compute_confidence(
                description_match=description_match,
                category_autofill=category_autofill,
                mode_detected=mode_detected,
                merchant_memory_hit=merchant_hit,
            )

            needs_attention = not category_autofill
            if needs_attention:
                attention_count += 1

            inserted_docs.append(
                {
                    "user_id": user_oid,
                    "source": source,
                    "account_id": account_oid,
                    "date": _combine_statement_date(row["date"]),
                    "amount": row["amount"],
                    "type": row["type"],
                    "description": row["description"],
                    "mode": row["mode"],
                    "category": suggestion.get("category_name") if suggestion else None,
                    "category_code": suggestion.get("category_code") if suggestion else None,
                    "subcategory_code": suggestion.get("subcategory_code") if suggestion else None,
                    "subcategory_name": suggestion.get("subcategory_name") if suggestion else None,
                    "merchant_keyword": merchant_keyword,
                    "confidence": confidence,
                    "needs_attention": needs_attention,
                    "fingerprint": fingerprint,
                    "status": "pending",
                    "raw_data": row.get("raw_data") or row,
                    "created_at": datetime.now(UTC),
                }
            )
            seen_batch.add(fingerprint)
            inserted_total += float(row["amount"])

        except Exception as exc:
            errors.append({
                "row": str(row)[:100],
                "error": str(exc)
            })

    inserted_count = len(inserted_docs)

    # Insert to database
    if inserted_docs:
        try:
            await db.transaction_inbox.insert_many(inserted_docs, ordered=False)
        except BulkWriteError as exc:
            write_errors = list((exc.details or {}).get("writeErrors") or [])
            duplicate_errors = sum(1 for error in write_errors if int(error.get("code") or 0) == 11000)
            if duplicate_errors:
                inserted_count = max(0, inserted_count - duplicate_errors)
                errors.append({"error": f"{duplicate_errors} rows had duplicate key errors"})

    return {
        "inserted_count": inserted_count,
        "duplicate_count": duplicates,
        "needs_attention_count": attention_count,
        "statement_total": round_money(statement_total),
        "inbox_total": round_money(inserted_total),
        "errors": errors,
    }


# =========================================================================
# PUBLIC API: Import Statement → Full Pipeline
# =========================================================================

async def import_statement_to_inbox(
    user_id: str,
    account_id: str,
    upload: UploadFile
) -> dict[str, Any]:
    """
    Full pipeline: Parse → Normalize → Insert to Buffer
    """
    user_oid = _user_oid(user_id)
    account_oid = _account_oid(account_id)

    # Verify account exists
    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None},
        {"_id": 1}
    )
    if not account:
        raise NotFoundError("Account not found")

    filename = (upload.filename or "").lower()
    source_format = "pdf" if filename.endswith(".pdf") else "csv"

    # STAGE 1: Parse
    raw_rows, parse_errors = await parse_statement_file(upload)
    if not raw_rows:
        raise ValidationError("No transactions could be extracted from this statement")

    # STAGE 2: Normalize
    normalized_rows, normalize_errors = await normalize_rows(raw_rows, source_format=source_format)
    if not normalized_rows:
        raise ValidationError(f"No valid transactions after normalization. Errors: {normalize_errors[:5]}")

    # STAGE 3: Insert to Buffer
    insert_result = await _insert_rows_to_buffer(user_oid, account_oid, "statement", normalized_rows)

    # Return detailed report
    return {
        "stage1_parsed": len(raw_rows),
        "stage1_errors": parse_errors,
        "stage2_normalized": len(normalized_rows),
        "stage2_sample": [
            {
                "date": row["date"].isoformat(),
                "amount": row["amount"],
                "type": row["type"],
                "description": row["description"],
                "mode": row["mode"],
            }
            for row in normalized_rows[:5]
        ],
        "stage2_errors": normalize_errors,
        "stage3_inserted": insert_result["inserted_count"],
        "stage3_duplicates": insert_result["duplicate_count"],
        "stage3_needs_attention": insert_result["needs_attention_count"],
        "stage3_errors": insert_result["errors"],
        "statement_total": insert_result["statement_total"],
        "inbox_total": insert_result["inbox_total"],
    }


# =========================================================================
# REST: Existing functionality maintained
# =========================================================================

def _serialize_inbox_row(row: dict[str, Any], account_name: str | None = None) -> dict[str, Any]:
    """Serialize inbox row for API response"""
    row_date = row.get("date")
    if isinstance(row_date, (datetime, date)):
        iso = row_date.isoformat()
    else:
        iso = ""
    
    return {
        "id": str(row["_id"]),
        "source": row.get("source", "statement"),
        "account_id": str(row.get("account_id") or ""),
        "account_name": account_name or "",
        "date": iso,
        "date_key": iso[:10] if iso else "",
        "amount": float(row.get("amount") or 0),
        "type": row.get("type") or "debit",
        "description": row.get("description") or "",
        "mode": row.get("mode") or "unknown",
        "category": row.get("category"),
        "category_code": row.get("category_code"),
        "subcategory_code": row.get("subcategory_code"),
        "subcategory_name": row.get("subcategory_name"),
        "confidence": int(row.get("confidence") or 0),
        "merchant_keyword": row.get("merchant_keyword"),
        "needs_attention": bool(row.get("needs_attention")),
        "status": row.get("status", "pending"),
    }


async def list_inbox_rows(user_id: str, only_attention: bool = False) -> dict[str, Any]:
    """List inbox rows with summary"""
    user_oid = _user_oid(user_id)
    query: dict[str, Any] = {"user_id": user_oid, "status": "pending"}
    if only_attention:
        query["needs_attention"] = True

    accounts_cursor = db.accounts.find({"user_id": user_oid, "deleted_at": None}, {"name": 1})
    account_map = {str(acc["_id"]): acc.get("name", "Account") async for acc in accounts_cursor}

    cursor = db.transaction_inbox.find(query).sort([("date", -1), ("created_at", -1)])
    rows: list[dict[str, Any]] = []
    attention_count = 0
    type_counts: Counter[str] = Counter()
    statement_total = 0.0
    inbox_total = 0.0

    async for row in cursor:
        serialized = _serialize_inbox_row(row, account_map.get(str(row.get("account_id") or ""), "Account"))
        rows.append(serialized)

        amount = float(serialized["amount"])
        inbox_total += amount
        if serialized["source"] == "statement":
            statement_total += amount

        if serialized["needs_attention"]:
            attention_count += 1
        type_counts[str(serialized["source"] or "statement")] += 1

    return {
        "rows": rows,
        "summary": {
            "pending_count": len(rows),
            "needs_attention_count": attention_count,
            "statement_count": type_counts.get("statement", 0),
            "sms_count": type_counts.get("sms", 0),
            "statement_total": round_money(statement_total),
            "inbox_total": round_money(inbox_total),
        },
    }


async def update_inbox_row(
    user_id: str,
    row_id: str,
    amount: float | None = None,
    description: str | None = None,
    tx_type: str | None = None,
    mode: str | None = None,
    category_code: str | None = None,
    subcategory_code: str | None = None,
    statement_date: str | None = None,
) -> dict[str, Any]:
    """Update pending inbox row"""
    user_oid = _user_oid(user_id)
    oid = _row_oid(row_id)

    row = await db.transaction_inbox.find_one({"_id": oid, "user_id": user_oid, "status": "pending"})
    if not row:
        raise NotFoundError("Inbox row not found")

    update: dict[str, Any] = {}

    next_type = tx_type or str(row.get("type") or "debit")
    if next_type not in {"debit", "credit"}:
        raise ValidationError("Type must be debit or credit")

    next_description = clean_description(description if description is not None else str(row.get("description") or ""))
    if not next_description:
        raise ValidationError("Description is required")

    next_amount = round_money(float(amount)) if amount is not None else float(row.get("amount") or 0)
    if next_amount <= 0:
        raise ValidationError("Amount must be positive")

    next_date_dt = row.get("date")
    if statement_date is not None:
        parsed = _parse_date_value(statement_date)
        if not parsed:
            raise ValidationError("Invalid date")
        next_date_dt = _combine_statement_date(parsed)
        update["date"] = next_date_dt

    next_date = next_date_dt.date() if isinstance(next_date_dt, datetime) else _parse_date_value(next_date_dt)
    if not next_date:
        raise ValidationError("Transaction date is required")

    next_mode = mode if mode is not None else detect_mode(next_description)
    next_category_code = str(row.get("category_code") or "").strip() or None
    next_subcategory_code = str(row.get("subcategory_code") or "").strip() or None

    update["description"] = next_description
    update["amount"] = next_amount
    update["type"] = next_type
    update["mode"] = next_mode
    update["merchant_keyword"] = extract_merchant_keyword(next_description)

    if category_code is not None:
        next_category_code = category_code.strip() or None
        update["category_code"] = next_category_code
        # Category change invalidates previously selected subcategory until reselected.
        next_subcategory_code = None
        update["subcategory_code"] = None
        update["subcategory_name"] = None

    if subcategory_code is not None:
        next_subcategory_code = subcategory_code.strip() or None

    if next_category_code and next_subcategory_code:
        subcategories = await get_subcategories(category_code=next_category_code, tx_type=next_type)
        if subcategories is None:
            raise ValidationError("Invalid category")

        matched = next((sub for sub in subcategories if str(sub.get("code")) == next_subcategory_code), None)
        if not matched:
            raise ValidationError("Invalid subcategory for selected category")

        update["subcategory_code"] = str(matched.get("code"))
        update["subcategory_name"] = str(matched.get("name") or matched.get("code"))
    elif next_category_code and subcategory_code is not None:
        update["subcategory_code"] = None
        update["subcategory_name"] = None
    elif not next_category_code:
        update["subcategory_code"] = None
        update["subcategory_name"] = None

    next_fingerprint = generate_fingerprint(next_date, next_amount)

    # Check for duplicates
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

    tx_fingerprints = await _existing_transaction_fingerprints(user_oid, [next_date])
    if next_fingerprint in tx_fingerprints:
        raise ValidationError("This row matches an existing transaction")

    update["fingerprint"] = next_fingerprint

    await db.transaction_inbox.update_one({"_id": oid}, {"$set": update})
    updated = await db.transaction_inbox.find_one({"_id": oid})

    return _serialize_inbox_row(updated)


async def approve_inbox_rows(user_id: str, row_ids: list[str], request=None) -> dict[str, Any]:
    """Approve selected inbox rows"""
    user_oid = _user_oid(user_id)
    valid_ids = [_row_oid(row_id) for row_id in row_ids]
    if not valid_ids:
        raise ValidationError("Select at least one inbox row")

    rows = await db.transaction_inbox.find(
        {
            "_id": {"$in": valid_ids},
            "user_id": user_oid,
            "status": "pending",
        }
    ).to_list(length=len(valid_ids))

    approved = 0
    failed: list[dict[str, str]] = []

    for row in rows:
        if not row.get("category_code") or not row.get("subcategory_code"):
            failed.append({"id": str(row["_id"]), "error": "Category is required before approval"})
            continue

        row_date = row.get("date")
        row_day = row_date.date() if isinstance(row_date, datetime) else _parse_date_value(row_date)
        if not row_day:
            failed.append({"id": str(row["_id"]), "error": "Transaction date is missing"})
            continue

        fingerprint = generate_fingerprint(row_day, float(row.get("amount") or 0))
        tx_fingerprints = await _existing_transaction_fingerprints(user_oid, [row_day])
        
        if fingerprint in tx_fingerprints:
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

            merchant_keyword = row.get("merchant_keyword") or extract_merchant_keyword(str(row.get("description") or ""))
            await _upsert_merchant_memory(
                user_oid,
                merchant_keyword,
                str(row["type"]),
                str(row["category_code"]),
                str(row.get("category") or ""),
                str(row["subcategory_code"]),
                str(row.get("subcategory_name") or ""),
            )

            approved += 1
        except Exception as exc:
            failed.append({"id": str(row["_id"]), "error": str(exc)})

    return {"approved_count": approved, "failed": failed}


async def discard_inbox_rows(user_id: str, row_ids: list[str]) -> dict[str, Any]:
    """Discard selected inbox rows"""
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


async def clear_pending_buffer(user_id: str) -> dict[str, int]:
    """Clear pending and discarded rows from user's inbox buffer"""
    user_oid = _user_oid(user_id)
    result = await db.transaction_inbox.delete_many(
        {"user_id": user_oid, "status": {"$in": ["pending", "discarded"]}}
    )
    return {"cleared_count": int(result.deleted_count)}


async def approve_high_confidence_rows(user_id: str, min_confidence: int = 70, request=None) -> dict[str, Any]:
    """Auto-approve rows with confidence >= min_confidence"""
    user_oid = _user_oid(user_id)
    rows = await db.transaction_inbox.find(
        {
            "user_id": user_oid,
            "status": "pending",
            "needs_attention": False,
            "confidence": {"$gte": int(min_confidence)},
        }
    ).to_list(length=500)

    if not rows:
        return {"approved_count": 0, "failed": []}

    approved = 0
    failed: list[dict[str, str]] = []

    for row in rows:
        if not row.get("category_code") or not row.get("subcategory_code"):
            failed.append({"id": str(row["_id"]), "error": "Category is required before approval"})
            continue

        row_date = row.get("date")
        row_day = row_date.date() if isinstance(row_date, datetime) else _parse_date_value(row_date)
        if not row_day:
            failed.append({"id": str(row["_id"]), "error": "Transaction date is missing"})
            continue

        fingerprint = generate_fingerprint(row_day, float(row.get("amount") or 0))
        tx_fingerprints = await _existing_transaction_fingerprints(user_oid, [row_day])
        
        if fingerprint in tx_fingerprints:
            await db.transaction_inbox.update_one(
                {"_id": row["_id"]},
                {"$set": {"status": "discarded", "discarded_at": datetime.now(UTC)}},
            )
            failed.append({"id": str(row["_id"]), "error": "Skipped because transaction already exists"})
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

            merchant_keyword = row.get("merchant_keyword") or extract_merchant_keyword(str(row.get("description") or ""))
            await _upsert_merchant_memory(
                user_oid,
                merchant_keyword,
                str(row["type"]),
                str(row["category_code"]),
                str(row.get("category") or ""),
                str(row["subcategory_code"]),
                str(row.get("subcategory_name") or ""),
            )

            approved += 1
        except Exception as exc:
            failed.append({"id": str(row["_id"]), "error": str(exc)})

    return {"approved_count": approved, "failed": failed}


# =========================================================================
# SMS FUNCTIONS
# =========================================================================

def _extract_sms_amount(body: str) -> float | None:
    """Extract amount from SMS body"""
    matches = list(SMS_AMOUNT_RE.finditer(body))
    if not matches:
        return None
    last = matches[-1]
    raw = last.group(1) or last.group(2)
    return _parse_amount(raw)


def _extract_sms_date(message: dict[str, Any]) -> date | None:
    """Extract date from SMS"""
    ts = message.get("timestamp")
    if isinstance(ts, (int, float)):
        seconds = ts / 1000 if ts > 2_000_000_000 else ts
        try:
            return datetime.fromtimestamp(seconds, tz=UTC).date()
        except Exception:
            pass

    body = _normalize_text(message.get("body") or "")
    date_match = DATE_TOKEN_RE.search(body)
    if date_match:
        parsed = _parse_date_value(date_match.group(1))
        if parsed:
            return parsed

    return datetime.now(UTC).date()


def _extract_sms_description(body: str) -> str:
    """Clean SMS description"""
    text = _normalize_text(body)
    text = re.sub(r"\b(?:debited|credited|spent|received)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:a/c|acct|account)\s*[xX*]*\d+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:avl|available)\s+bal(?:ance)?\b.*$", "", text, flags=re.IGNORECASE)
    cleaned = clean_description(text)
    return cleaned or "Bank SMS Transaction"


def _normalize_sms_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a single SMS message to transaction format"""
    body = _normalize_text(message.get("body") or "")
    if not body:
        return None

    amount = _extract_sms_amount(body)
    if amount is None or amount <= 0:
        return None

    row_date = _extract_sms_date(message)
    description = _extract_sms_description(body)
    tx_type = infer_type_from_description(description)
    mode = detect_mode(description)

    return {
        "date": row_date,
        "amount": amount,
        "type": tx_type,
        "description": description,
        "mode": mode,
        "raw_data": {
            "address": message.get("address"),
            "body": body,
            "timestamp": message.get("timestamp"),
        },
    }


async def ingest_sms_to_inbox(
    user_id: str,
    account_id: str,
    messages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Ingest SMS messages directly to inbox"""
    user_oid = _user_oid(user_id)
    account_oid = _account_oid(account_id)

    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None},
        {"_id": 1}
    )
    if not account:
        raise NotFoundError("Account not found")

    normalized = [row for row in (_normalize_sms_message(msg) for msg in messages) if row]
    if not normalized:
        raise ValidationError("No valid SMS transactions were found")

    insert_result = await _insert_rows_to_buffer(user_oid, account_oid, "sms", normalized)
    
    return {
        "inserted_count": insert_result["inserted_count"],
        "duplicate_count": insert_result["duplicate_count"],
        "needs_attention_count": insert_result["needs_attention_count"],
        "statement_total": insert_result["statement_total"],
        "inbox_total": insert_result["inbox_total"],
        "errors": insert_result["errors"],
    }


async def parse_sms_buffer_to_inbox(user_id: str, account_id: str, limit: int = 250) -> dict[str, Any]:
    """Parse buffered SMS messages to inbox"""
    user_oid = _user_oid(user_id)
    account_oid = _account_oid(account_id)

    account = await db.accounts.find_one(
        {"_id": account_oid, "user_id": user_oid, "deleted_at": None},
        {"_id": 1}
    )
    if not account:
        raise NotFoundError("Account not found")

    docs = await db.sms_buffer.find(
        {"user_id": user_oid, "parsed": {"$ne": True}}
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    
    if not docs:
        return {
            "inserted_count": 0,
            "duplicate_count": 0,
            "needs_attention_count": 0,
            "statement_total": 0.0,
            "inbox_total": 0.0,
            "errors": [],
        }

    messages = [
        {
            "address": doc.get("address"),
            "body": doc.get("body") or doc.get("text"),
            "timestamp": doc.get("timestamp") or doc.get("created_at"),
        }
        for doc in docs
    ]

    result = await ingest_sms_to_inbox(user_id=user_id, account_id=account_id, messages=messages)

    ids = [doc.get("_id") for doc in docs if doc.get("_id")]
    if ids:
        await db.sms_buffer.update_many(
            {"_id": {"$in": ids}},
            {"$set": {"parsed": True, "parsed_at": datetime.now(UTC)}},
        )

    return result


async def clear_sms_buffer(user_id: str) -> dict[str, int]:
    """Clear SMS buffer for user"""
    user_oid = _user_oid(user_id)
    result = await db.sms_buffer.delete_many({"user_id": user_oid})
    return {"cleared_count": int(result.deleted_count)}
