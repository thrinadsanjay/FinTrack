from app.db.mongo import db

async def init_indexes():
    # Users
    await db.users.create_index("email", unique=True)
    # Accounts
    await db.accounts.create_index([("user_id", 1)])
    await db.accounts.create_index([("user_id", 1), ("name", 1)], unique=True, name="unique_account_name_per_user")
    # Audit Logs
    await db.audit_logs.create_index([("user_id", 1)])
    await db.audit_logs.create_index({ "action": 1 })
    await db.audit_logs.create_index([("timestamp", -1)])
    # await db.audit_logs.createIndex({ user_id: 1, timestamp: -1 })
    # await db.audit_logs.createIndex({ action: 1, timestamp: -1 })

    # Transactions
    await db.transactions.create_index([("user_id", 1)])
    await db.transactions.create_index([("account_id", 1)])
    await db.transactions.create_index([("created_at", -1)])

    # Notifications
    await db.notifications.create_index([("user_id", 1)])
    await db.notifications.create_index([("user_id", 1), ("is_read", 1)])
    await db.notifications.create_index([("user_id", 1), ("key", 1)], unique=True)

    
    
