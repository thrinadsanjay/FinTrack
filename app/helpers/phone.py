from __future__ import annotations

import re
DEFAULT_PHONE_COUNTRY = "IN"
DEFAULT_COUNTRY_CALLING_CODE = "+91"

COUNTRY_TIMEZONE_MAP: dict[str, str] = {
    "IN": "Asia/Kolkata",
    "US": "America/New_York",
    "CA": "America/Toronto",
    "GB": "Europe/London",
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
    "SG": "Asia/Singapore",
    "MY": "Asia/Kuala_Lumpur",
    "AE": "Asia/Dubai",
    "SA": "Asia/Riyadh",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "ES": "Europe/Madrid",
    "ZA": "Africa/Johannesburg",
    "NG": "Africa/Lagos",
    "BR": "America/Sao_Paulo",
    "MX": "America/Mexico_City",
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "PK": "Asia/Karachi",
    "BD": "Asia/Dhaka",
    "LK": "Asia/Colombo",
    "NP": "Asia/Kathmandu",
    "ID": "Asia/Jakarta",
    "PH": "Asia/Manila",
    "TR": "Europe/Istanbul",
    "IT": "Europe/Rome",
    "NL": "Europe/Amsterdam",
    "CH": "Europe/Zurich",
    "RU": "Europe/Moscow",
}
DEFAULT_COUNTRY_TIMEZONE = "Asia/Kolkata"
PHONE_COUNTRIES: list[dict[str, str]] = [
    {"iso": "IN", "label": "India", "code": "+91"},
    {"iso": "US", "label": "United States", "code": "+1"},
    {"iso": "CA", "label": "Canada", "code": "+1"},
    {"iso": "GB", "label": "United Kingdom", "code": "+44"},
    {"iso": "AU", "label": "Australia", "code": "+61"},
    {"iso": "NZ", "label": "New Zealand", "code": "+64"},
    {"iso": "SG", "label": "Singapore", "code": "+65"},
    {"iso": "MY", "label": "Malaysia", "code": "+60"},
    {"iso": "AE", "label": "United Arab Emirates", "code": "+971"},
    {"iso": "SA", "label": "Saudi Arabia", "code": "+966"},
    {"iso": "DE", "label": "Germany", "code": "+49"},
    {"iso": "FR", "label": "France", "code": "+33"},
    {"iso": "ES", "label": "Spain", "code": "+34"},
    {"iso": "ZA", "label": "South Africa", "code": "+27"},
    {"iso": "NG", "label": "Nigeria", "code": "+234"},
    {"iso": "BR", "label": "Brazil", "code": "+55"},
    {"iso": "MX", "label": "Mexico", "code": "+52"},
    {"iso": "JP", "label": "Japan", "code": "+81"},
    {"iso": "KR", "label": "South Korea", "code": "+82"},
    {"iso": "PK", "label": "Pakistan", "code": "+92"},
    {"iso": "BD", "label": "Bangladesh", "code": "+880"},
    {"iso": "LK", "label": "Sri Lanka", "code": "+94"},
    {"iso": "NP", "label": "Nepal", "code": "+977"},
    {"iso": "ID", "label": "Indonesia", "code": "+62"},
    {"iso": "PH", "label": "Philippines", "code": "+63"},
    {"iso": "TR", "label": "Turkey", "code": "+90"},
    {"iso": "IT", "label": "Italy", "code": "+39"},
    {"iso": "NL", "label": "Netherlands", "code": "+31"},
    {"iso": "CH", "label": "Switzerland", "code": "+41"},
    {"iso": "RU", "label": "Russia", "code": "+7"},
]

_PHONE_COUNTRY_BY_ISO = {item["iso"]: item for item in PHONE_COUNTRIES}
_PHONE_COUNTRY_BY_CODE = {}
for item in PHONE_COUNTRIES:
    _PHONE_COUNTRY_BY_CODE.setdefault(item["code"], []).append(item)


def normalize_country_iso(value: str | None) -> str:
    iso = str(value or "").strip().upper()
    if iso and iso in _PHONE_COUNTRY_BY_ISO:
        return iso
    return DEFAULT_PHONE_COUNTRY


def country_code_from_iso(value: str | None) -> str:
    return _PHONE_COUNTRY_BY_ISO.get(normalize_country_iso(value), {}).get("code", DEFAULT_COUNTRY_CALLING_CODE)


def country_iso_from_timezone(value: str | None) -> str:
    timezone_name = str(value or "").strip()
    for iso, timezone_value in COUNTRY_TIMEZONE_MAP.items():
        if timezone_value == timezone_name:
            return iso
    return DEFAULT_PHONE_COUNTRY


def timezone_from_country_iso(value: str | None) -> str:
    return COUNTRY_TIMEZONE_MAP.get(normalize_country_iso(value), DEFAULT_COUNTRY_TIMEZONE)


def normalize_country_code(value: str | None) -> str:
    code = str(value or "").strip()
    if not code:
        return DEFAULT_COUNTRY_CALLING_CODE
    if not code.startswith("+"):
        code = "+" + code.lstrip("+")
    code = "+" + re.sub(r"[^0-9]", "", code)
    return code if code != "+" else DEFAULT_COUNTRY_CALLING_CODE


def normalize_local_number(value: str | None) -> str:
    return re.sub(r"[^0-9]", "", str(value or "").strip())


def normalize_phone_number(
    mobile: str | None = None,
    country_iso: str | None = None,
    country_code: str | None = None,
    local_number: str | None = None,
    default_country_iso: str | None = None,
) -> str:
    raw_mobile = re.sub(r"[\s\-()]", "", str(mobile or "").strip())
    if raw_mobile:
        if raw_mobile.startswith("+"):
            raw_mobile = "+" + re.sub(r"[^0-9]", "", raw_mobile)
        elif raw_mobile.isdigit():
            default_code = country_code_from_iso(default_country_iso) if default_country_iso else DEFAULT_COUNTRY_CALLING_CODE
            raw_mobile = f"{default_code}{raw_mobile}"
        return raw_mobile

    code = normalize_country_code(country_code) if country_code else country_code_from_iso(country_iso or default_country_iso)
    local = normalize_local_number(local_number)
    if not local:
        return ""
    return f"{code}{local}"


def country_items() -> list[dict[str, str]]:
    return PHONE_COUNTRIES
