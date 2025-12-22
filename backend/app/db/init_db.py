from app.db.mongo import db

async def init_indexes():
    # Users
    await db.users.create_index("keycloak_id", unique=True)
    # Accounts
    await db.accounts.create_index([("user_id", 1)])
    # Audit Logs
    await db.audit_logs.create_index([("user_id", 1)])
    await db.audit_logs.create_index([("timestamp", -1)])
    # Transactions
    await db.transactions.create_index([("user_id", 1)])
    await db.transactions.create_index([("account_id", 1)])
    await db.transactions.create_index([("created_at", -1)])