from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from app.services.audit import audit_log
from app.db.mongo import db
from app.db.init_db import init_indexes
from app.routers import health, auth, accounts, transactions, categories
from app.core.startup import ensure_admin_exists, define_categories
from app.core.logging import setup_logging
from app.core.session import add_session_middleware
from app.core.config import settings
from app.web.templates import templates
from app.web.home import router as web_router
from app.web.auth import router as web_auth_router
from app.web.accounts import router as web_accounts_router
from app.web.transactions import router as web_transactions_router
import logging

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=f"{settings.APP_NAME}",
    version=f"${settings.APP_VERSION}",
    environment=f"${settings.ENV}",
)
logger.info("⚙️ Starting Application...")

print(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} in {settings.ENV} environment.")
logging.getLogger("httpx").setLevel(logging.DEBUG)

# Static assets
app.mount("/static", StaticFiles(directory="app/frontend/static"), name="static")


# API routes
app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["Accounts"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(categories.router, prefix="/api/categories", tags=["Categories"])

# Web routes
add_session_middleware(app)
app.include_router(web_router)
app.include_router(web_auth_router)
app.include_router(web_accounts_router, prefix="/accounts")
app.include_router(web_transactions_router, prefix="/transactions")

# Startup Event
@app.on_event("startup")
async def startup_indexes():
    logger.info("⚙️ Running Inital Setup...")
    await init_indexes()
    await ensure_admin_exists()
    await define_categories()

# Debug route to list all registered routes
@app.get("/__debug/routes")
def debug_routes():
    lines = []
    for r in app.routes:
        if hasattr(r, "path"):
            lines.append(f"{r.path} {getattr(r, 'methods', '')}")
    return PlainTextResponse("\n".join(lines))

