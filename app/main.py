import logging

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler


from app.core.config import settings
from app.core.logging import setup_logging
from app.core.session import add_session_middleware
from app.core.startup import ensure_admin_exists, define_categories

from app.db.init_db import init_indexes

from app.routers import health, auth, accounts, transactions, categories, recurring_deposit
from app.web.home import router as web_router
from app.web.auth import router as web_auth_router
from app.web.accounts import router as web_accounts_router
from app.web.transactions import router as web_transactions_router
from app.web.notifications import router as web_notifications_router

from app.schedulers.recurring_scheduler import run_recurring_transactions



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


# ======================================================
# SCHEDULER
# ======================================================

scheduler = AsyncIOScheduler(timezone="UTC")


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
        hour=2,
        minute=30, # Run daily at 12:10 PM UTC
        id="recurring-transactions",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("⏱ Recurring transaction scheduler started")


@app.on_event("shutdown")
def on_shutdown():
    logger.info("🛑 Shutting down scheduler...")
    scheduler.shutdown(wait=False)


# ======================================================
# DEBUG ROUTES
# ======================================================

@app.get("/__debug/routes", include_in_schema=False)
def debug_routes():
    lines = [
        f"{route.path} {getattr(route, 'methods', '')}"
        for route in app.routes
        if hasattr(route, "path")
    ]
    return PlainTextResponse("\n".join(lines))
