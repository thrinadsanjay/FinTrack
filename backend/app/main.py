from fastapi import FastAPI
from app.routers import health, auth, accounts, transactions, categories
from app.core.logging import setup_logging
from app.db.mongo import db
from app.db.init_db import init_indexes

setup_logging()

app = FastAPI(
    title="${PROJECT_NAME}",
    version="${PROJECT_VERSION}",
)

@app.on_event("startup")
async def startup_indexes():
    await init_indexes()


app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(accounts.router, prefix="/accounts", tags=["Accounts"])
app.include_router(transactions.router, prefix="/transactions", tags=["Transactions"])
app.include_router(categories.router, prefix="/categories", tags=["Categories"])
