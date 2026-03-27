import logging
import os
import time
import html
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, REGISTRY
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.metrics import track_request
from app.services.users import count_active_users_total
from app.services.metrics import set_total_users
from app.services.admin_settings import get_maintenance_state, get_admin_settings

from app.core.config import settings
from app.core.csrf import CsrfValidationError
from app.core.errors import AppError
from app.core.logging import setup_logging
from app.core.session import add_session_middleware
from app.core.startup import ensure_admin_exists, define_categories

from app.db.init_db import init_indexes

from app.routers import (
    health,
    auth,
    accounts,
    transactions,
    categories,
    recurring_deposit,
    chat,
    ai_chat,
    telegram_bot,
)
from app.web.home import router as web_router
from app.web.auth import router as web_auth_router
from app.web.accounts import router as web_accounts_router
from app.web.transactions import router as web_transactions_router
from app.web.notifications import router as web_notifications_router
from app.web.recurring import router as web_recurring_router
from app.web.profile import router as web_profile_router
from app.web.admin import router as web_admin_router
from app.web.help_support import router as web_help_support_router
from app.web.templates import templates

from app.schedulers.recurring_scheduler import configure_recurring_schedule, run_recurring_transactions
from app.schedulers.notification_scheduler import run_notification_alert_sweep
from app.schedulers.backup_scheduler import configure_backup_schedule
from app.services.telegram_polling import run_telegram_poll_once



# ======================================================
# LOGGING
# ======================================================

setup_logging()
logger = logging.getLogger(__name__)

if settings.FT_ENV.lower() in ("dev", "development"):
    logging.getLogger("httpx").setLevel(logging.DEBUG)


# ======================================================
# APPLICATION
# ======================================================

app = FastAPI(
    title=settings.FT_APP_NAME,
    version=settings.FT_APP_VERSION,
    FT_ENVironments=settings.FT_ENV,
)

logger.info(
    "🚀 Starting %s v%s [%s]",
    settings.FT_APP_NAME,
    settings.FT_APP_VERSION,
    settings.FT_ENV,
)


# ======================================================
# STATIC FILES
# ======================================================

app.mount(
    "/static",
    StaticFiles(directory="app/frontend/static"),
    name="static",
)


# ======================================================
# SESSION MIDDLEWARE
# ======================================================

add_session_middleware(app)

# ======================================================
# ADD PROMETHEUS METRICS ENDPOINT
# ======================================================

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start_time = time.time()
    maintenance = {"enabled": False, "message": ""}
    try:
        maintenance = await get_maintenance_state()
    except Exception:
        logger.exception("Failed to read maintenance state")

    request.state.maintenance_mode = bool(maintenance.get("enabled"))
    request.state.maintenance_message = (maintenance.get("message") or "").strip()

    try:
        admin_settings = await get_admin_settings()
        app_cfg = (admin_settings or {}).get("application") or {}
        auth_cfg = (admin_settings or {}).get("authentication") or {}
        request.state.telegram_default_country = str(
            app_cfg.get("default_country")
            or auth_cfg.get("default_telegram_country")
            or "IN"
        ).strip() or "IN"
    except Exception:
        request.state.telegram_default_country = "IN"

    client_tz = str(request.cookies.get("ft_tz") or "").strip()
    if client_tz:
        try:
            ZoneInfo(client_tz)
            if request.session.get("timezone") != client_tz:
                request.session["timezone"] = client_tz
        except Exception:
            pass

    if request.state.maintenance_mode and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        path = request.url.path
        normalized_path = path.rstrip("/") or "/"
        allow_writes = normalized_path in {
            "/admin/settings",
            "/login/local",
            "/reset-password",
            "/notifications/read",
        }
        if not allow_writes:
            maintenance_message = request.state.maintenance_message or (
                "Maintenance mode is active. Write operations are temporarily disabled."
            )
            accept = request.headers.get("accept", "")
            if "text/html" in accept:
                safe_message = html.escape(maintenance_message, quote=True)
                response = HTMLResponse(
                    f"<h1>Maintenance Mode</h1><p>{safe_message}</p>",
                    status_code=503
                )
            else:
                response = JSONResponse({"detail": maintenance_message}, status_code=503)
            duration = time.time() - start_time
            track_request(
                method=request.method,
                endpoint=request.url.path,
                status=response.status_code,
                duration=duration,
            )
            return response

    response = await call_next(request)

    duration = time.time() - start_time

    track_request(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
        duration=duration
    )

    return response

@app.get("/metrics")
def metrics():
    return Response(
        generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST
    )

# ======================================================
# API ROUTES
# ======================================================

app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["Accounts"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(categories.router, prefix="/api/categories", tags=["Categories"])
app.include_router(recurring_deposit.router, prefix="/api/recurring-deposits", tags=["Recurring Deposits"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(ai_chat.router, prefix="/api/aichat", tags=["AI Chat"])
app.include_router(telegram_bot.router, prefix="/api/telegram", tags=["Telegram"])

# WEB ROUTES
app.include_router(web_router)
app.include_router(web_auth_router)
app.include_router(web_accounts_router, prefix="/accounts")
app.include_router(web_transactions_router, prefix="/transactions")
app.include_router(web_notifications_router, prefix="/notifications")
app.include_router(web_recurring_router, prefix="/recurring")
app.include_router(web_profile_router)
app.include_router(web_admin_router, prefix="/admin")
app.include_router(web_help_support_router)


# ======================================================
# SCHEDULER
# ======================================================

scheduler = AsyncIOScheduler(timezone="UTC")
app.state.scheduler = scheduler
notification_alert_interval_seconds = max(
    60,
    int(os.getenv("FT_NOTIFICATION_ALERT_INTERVAL_SECONDS", "300")),
)

# ======================================================
# STARTUP / SHUTDOWN
# ======================================================

@app.on_event("startup")
async def on_startup():
    logger.info("⚙️ Running initial setup...")

    await init_indexes()
    await ensure_admin_exists()
    await define_categories()
    try:
        set_total_users(await count_active_users_total())
    except Exception:
        logger.exception("Failed to initialize total user metric")

    await configure_recurring_schedule(scheduler)

    scheduler.add_job(
        run_telegram_poll_once,
        trigger="interval",
        seconds=8,
        id="telegram-polling",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        run_notification_alert_sweep,
        trigger="interval",
        seconds=notification_alert_interval_seconds,
        id="notification-alert-sweep",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    await configure_backup_schedule(scheduler)
    scheduler.start()
    logger.info(
        "⏱ Background schedulers started (recurring + telegram polling + notification sweep/%ss)",
        notification_alert_interval_seconds,
    )


@app.on_event("shutdown")
def on_shutdown():
    logger.info("🛑 Shutting down scheduler...")
    scheduler.shutdown(wait=False)


@app.exception_handler(CsrfValidationError)
async def csrf_exception_handler(request: Request, exc: CsrfValidationError):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return templates.TemplateResponse(
            "csrf_error.html",
            {
                "request": request,
                "error": str(exc),
            },
            status_code=403,
        )
    return JSONResponse({"detail": str(exc)}, status_code=403)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return templates.TemplateResponse(
            "app_error.html",
            {
                "request": request,
                "error": exc.detail,
            },
            status_code=exc.status_code,
        )
    payload = {"detail": exc.detail}
    if exc.code:
        payload["code"] = exc.code
    return JSONResponse(payload, status_code=exc.status_code)
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # NEVER pass request / exc / dict to logger
    logger.error(
        "Unhandled application error | path=%s | error=%s",
        request.url.path,
        str(exc),
    )

    accept = request.headers.get("accept", "")

    if "text/html" in accept:
        try:
            return templates.TemplateResponse(
                "app_error.html",
                {
                    "request": request,
                    "error": "Unexpected error occurred. Please retry.",
                },
                status_code=500,
            )
        except Exception:
            return PlainTextResponse(
                "Unexpected error. Please retry.",
                status_code=500,
            )

    return JSONResponse(
        {"detail": "Internal server error"},
        status_code=500,
    )
#@app.exception_handler(Exception)
#async def unhandled_exception_handler(request: Request, exc: Exception):
#    logger.exception("Unhandled application error on %s", request.url.path, exc_info=exc)
#    accept = request.headers.get("accept", "")
#    if "text/html" in accept:
#        try:
#            return templates.TemplateResponse(
#                "app_error.html",
#                {
#                    "request": request,
#                    "error": str(exc),
#                },
#                status_code=500,
#            )
#        except Exception:
#            return PlainTextResponse("Unexpected error. Please retry.", status_code=500)
#    return JSONResponse({"detail": "Internal server error"}, status_code=500)


# ======================================================
# DEBUG ROUTES
# ======================================================

if not settings.is_production:
    @app.get("/__debug/routes", include_in_schema=False)
    def debug_routes():
        lines = [
            f"{route.path} {getattr(route, 'methods', '')}"
            for route in app.routes
            if hasattr(route, "path")
        ]
        return PlainTextResponse("\n".join(lines))
