"""Shared display labels so pages do not invent their own casing or device copy."""

from __future__ import annotations

import re

PAYMENT_MODE_LABELS = {
    "upi": "UPI",
    "neft": "NEFT",
    "imps": "IMPS",
    "rtgs": "RTGS",
    "sip": "SIP",
    "emi": "EMI",
    "netbanking": "Net Banking",
    "net_banking": "Net Banking",
    "card": "Card",
    "cash": "Cash",
    "wallet": "Wallet",
    "cheque": "Cheque",
    "check": "Cheque",
    "bank_transfer": "Bank Transfer",
    "transfer": "Transfer",
    "unknown": "Unknown",
    "other": "Other",
}

HEALTH_BAND_LABELS = {
    "excellent": "Excellent",
    "good": "Good",
    "fair": "Fair",
    "watch": "Watch",
    "risk": "Risk",
    "insufficient": "Insufficient data",
}


ACCOUNT_TYPE_LABELS = {
    "savings": "Savings",
    "current": "Current",
    "wallet": "Wallet",
    "cash": "Cash",
    "investment": "Investment",
    "credit_card": "Credit card",
    "loan": "Loan",
    "other": "Other",
}


def account_type_label(acc_type: str | None) -> str:
    key = str(acc_type or "").strip().lower()
    if key in ACCOUNT_TYPE_LABELS:
        return ACCOUNT_TYPE_LABELS[key]
    return key.replace("_", " ").title() or "Account"


def payment_mode_label(mode: str | None) -> str:
    key = re.sub(r"[\s-]+", "_", str(mode or "").strip().lower())
    if key in PAYMENT_MODE_LABELS:
        return PAYMENT_MODE_LABELS[key]
    if not key:
        return ""
    return key.replace("_", " ").title()


def health_band_label(band: str | None) -> str:
    key = str(band or "").strip().lower()
    if key in HEALTH_BAND_LABELS:
        return HEALTH_BAND_LABELS[key]
    return (band or "").replace("_", " ").title() or "Insufficient data"


def user_agent_label(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "Unknown device"
    blob = text.lower()
    browser = "Browser"
    if "edg/" in blob or "edge/" in blob:
        browser = "Edge"
    elif "firefox/" in blob:
        browser = "Firefox"
    elif "crios/" in blob or "chrome/" in blob:
        browser = "Chrome"
    elif "safari/" in blob and "chrome/" not in blob:
        browser = "Safari"
    elif "opera" in blob or "opr/" in blob:
        browser = "Opera"

    system = "Unknown OS"
    if "android" in blob:
        system = "Android"
    elif "iphone" in blob or "ipad" in blob or "ios" in blob:
        system = "iOS"
    elif "mac os" in blob or "macintosh" in blob:
        system = "macOS"
    elif "windows" in blob:
        system = "Windows"
    elif "cros" in blob:
        system = "ChromeOS"
    elif "linux" in blob or "x11" in blob:
        system = "Linux"
    return f"{browser} on {system}"


_BROWSERS = (
    # (name, version regex, font-awesome icon). Order matters: Edge/Opera UAs also contain "Chrome".
    ("Edge", r"edg(?:e|a|ios)?/([\d.]+)", "fa-brands fa-edge"),
    ("Opera", r"(?:opr|opera)/([\d.]+)", "fa-brands fa-opera"),
    ("Firefox", r"(?:firefox|fxios)/([\d.]+)", "fa-brands fa-firefox-browser"),
    ("Chrome", r"(?:chrome|crios)/([\d.]+)", "fa-brands fa-chrome"),
    ("Safari", r"version/([\d.]+).*safari/", "fa-brands fa-safari"),
)


def parse_user_agent(value: str | None) -> dict:
    """
    Human-readable browser/OS for session lists, e.g. "Firefox 117.0 (Linux)".
    Returns {"label", "browser", "version", "os", "icon", "mobile"}.
    """
    import re

    text = str(value or "").strip()
    if not text:
        return {"label": "Unknown device", "browser": None, "version": None, "os": None,
                "icon": "fa-solid fa-display", "mobile": False}
    blob = text.lower()

    browser, version, icon = None, None, "fa-solid fa-globe"
    for name, pattern, fa in _BROWSERS:
        match = re.search(pattern, blob)
        if match:
            browser, icon = name, fa
            parts = match.group(1).split(".")
            version = ".".join(parts[:2]) if len(parts) > 1 else parts[0]
            break

    if "android" in blob:
        system = "Android"
    elif "iphone" in blob or "ipad" in blob or " ios" in blob:
        system = "iOS"
    elif "mac os" in blob or "macintosh" in blob:
        system = "macOS"
    elif "windows" in blob:
        system = "Windows"
    elif "cros" in blob:
        system = "ChromeOS"
    elif "linux" in blob or "x11" in blob:
        system = "Linux"
    else:
        system = None

    head = f"{browser} {version}" if browser and version else (browser or "Unknown browser")
    label = f"{head} ({system})" if system else head
    return {
        "label": label,
        "browser": browser,
        "version": version,
        "os": system,
        "icon": icon,
        "mobile": system in {"Android", "iOS"} or "mobile" in blob,
    }
