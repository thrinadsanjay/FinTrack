# app/services/metrics.py

import threading
from prometheus_client import Counter, Histogram, Gauge

# -----------------------------
# HTTP Metrics
# -----------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "fintracker_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)

HTTP_REQUEST_DURATION = Histogram(
    "fintracker_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)

# -----------------------------
# Business Metrics
# -----------------------------

TRANSACTIONS_TOTAL = Counter(
    "fintracker_transactions_total",
    "Total transactions created"
)

ACTIVE_USERS = Gauge(
    "fintracker_active_users",
    "Currently active logged-in users"
)

TOTAL_USERS = Gauge(
    "fintracker_total_users",
    "Total active users in FinTracker"
)

_ACTIVE_USER_IDS: set[str] = set()
_ACTIVE_LOCK = threading.Lock()

# -----------------------------
# Helper Functions
# -----------------------------

def track_request(method: str, endpoint: str, status: int, duration: float):
    HTTP_REQUESTS_TOTAL.labels(
        method=method,
        endpoint=endpoint,
        status=status
    ).inc()

    HTTP_REQUEST_DURATION.labels(
        method=method,
        endpoint=endpoint
    ).observe(duration)


def increment_transaction():
    TRANSACTIONS_TOTAL.inc()


def set_active_users(count: int):
    ACTIVE_USERS.set(count)


def set_total_users(count: int):
    TOTAL_USERS.set(max(0, int(count)))


def mark_user_logged_in(user_id: str):
    if not user_id:
        return
    with _ACTIVE_LOCK:
        _ACTIVE_USER_IDS.add(str(user_id))
        ACTIVE_USERS.set(len(_ACTIVE_USER_IDS))


def mark_user_logged_out(user_id: str):
    if not user_id:
        return
    with _ACTIVE_LOCK:
        _ACTIVE_USER_IDS.discard(str(user_id))
        ACTIVE_USERS.set(len(_ACTIVE_USER_IDS))
