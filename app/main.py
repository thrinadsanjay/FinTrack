import logging
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from apscheduler.schedulers.asyncio import AsyncIOScheduler


from app.core.config import settings
from app.core.csrf import CsrfValidationError
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
)
from app.web.home import router as web_router
from app.web.auth import router as web_auth_router
from app.web.accounts import router as web_accounts_router
from app.web.transactions import router as web_transactions_router
from app.web.notifications import router as web_notifications_router
from app.web.recurring import router as web_recurring_router
from app.web.profile import router as web_profile_router
from app.web.templates import templates

from app.schedulers.recurring_scheduler import run_recurring_transactions

from app.helpers.recurring_schedule import parse_scheduler_time


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
# API ROUTES
# ======================================================

app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["Accounts"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(categories.router, prefix="/api/categories", tags=["Categories"])
app.include_router(recurring_deposit.router, prefix="/api/recurring-deposits", tags=["Recurring Deposits"])


# WEB ROUTES
app.include_router(web_router)
app.include_router(web_auth_router)
app.include_router(web_accounts_router, prefix="/accounts")
app.include_router(web_transactions_router, prefix="/transactions")
app.include_router(web_notifications_router, prefix="/notifications")
app.include_router(web_recurring_router, prefix="/recurring")
app.include_router(web_profile_router)


# ======================================================
# SCHEDULER
# ======================================================

scheduler = AsyncIOScheduler(timezone="UTC")
run_time = os.getenv("SCHEDULER_RUN_TIME", "5:41 AM IST")
hour, minute, timezone = parse_scheduler_time(run_time)

# ======================================================
# STARTUP / SHUTDOWN
# ======================================================

@app.on_event("startup")
async def on_startup():
    logger.info("⚙️ Running initial setup...")

    await init_indexes()
    await ensure_admin_exists()
    await define_categories()

    scheduler.add_job(
        run_recurring_transactions,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=timezone,
        id="recurring-transactions",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("⏱ Recurring transaction scheduler started")


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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error on %s", request.url.path, exc_info=exc)
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        try:
            return templates.TemplateResponse(
                "app_error.html",
                {
                    "request": request,
                    "error": str(exc),
                },
                status_code=500,
            )
        except Exception:
            return PlainTextResponse("Unexpected error. Please retry.", status_code=500)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


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
