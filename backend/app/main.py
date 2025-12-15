from fastapi import FastAPI
from app.routers import health, auth, accounts, transactions, categories
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(
    title="Finance Tracker API",
    version="0.1.0",
)

app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(accounts.router, prefix="/accounts", tags=["Accounts"])
app.include_router(transactions.router, prefix="/transactions", tags=["Transactions"])
app.include_router(categories.router, prefix="/categories", tags=["Categories"])
