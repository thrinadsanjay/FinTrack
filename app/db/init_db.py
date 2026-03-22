from app.db.mongo import db


async def init_indexes():
    # Users
    await db.users.create_index("email", unique=True)
    await db.users.create_index([("passkeys.credential_id", 1)], unique=True, sparse=True)
    # Accounts
    await db.accounts.create_index([("user_id", 1)])
    # Drop legacy unique index on name (if exists) to avoid cross-user collisions
    existing = await db.accounts.index_information()
    if "name_1" in existing:
        await db.accounts.drop_index("name_1")
    await db.accounts.create_index(
        [("user_id", 1), ("name", 1)],
        unique=True,
        name="unique_account_name_per_user",
    )
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
    await db.transactions.create_index([("recurring_id", 1), ("scheduled_for", 1)])
    await db.transactions.create_index([("retry_of", 1)])
    await db.transactions.create_index([("is_failed", 1), ("retry_status", 1)])

    # Recurring rules / scheduler
    await db.recurring_deposits.create_index([("user_id", 1)])
    await db.recurring_deposits.create_index([("is_active", 1), ("next_run", 1)])
    await db.recurring_deposits.create_index([("user_id", 1), ("is_active", 1), ("next_run", 1)])

    # Notifications
    await db.notifications.create_index([("user_id", 1)])
    await db.notifications.create_index([("user_id", 1), ("is_read", 1)])
    await db.notifications.create_index([("user_id", 1), ("updated_at", -1)])
    await db.notifications.create_index([("user_id", 1), ("key", 1)], unique=True)

    # Web push subscriptions
    await db.push_subscriptions.create_index([("user_id", 1), ("is_active", 1)])
    await db.push_subscriptions.create_index([("endpoint", 1)], unique=True)
    await db.push_subscriptions.create_index([("fcm_token", 1)], unique=True, sparse=True)
    await db.push_subscriptions.create_index([("provider", 1), ("updated_at", -1)])
    await db.push_subscriptions.create_index([("updated_at", -1)])

    # Chat / support messages
    await db.chat_logs.create_index([("channel", 1), ("timestamp", -1)])
    await db.chat_logs.create_index([("channel", 1), ("user_id", 1), ("timestamp", -1)])
    await db.chat_logs.create_index([("channel", 1), ("user_id", 1), ("sender", 1), ("admin_read", 1)])
    await db.chat_logs.create_index([("channel", 1), ("user_id", 1), ("sender", 1), ("user_read", 1)])
    await db.support_sessions.create_index([("user_id", 1), ("updated_at", -1)])
    await db.support_sessions.create_index([("status", 1), ("updated_at", -1)])

    # Telegram OTP verification
    await db.telegram_otp_verifications.create_index([("user_id", 1)], unique=True)
    await db.telegram_otp_verifications.create_index([("expires_at", 1)], expireAfterSeconds=0)
    await db.telegram_register_intents.create_index([("chat_id", 1)], unique=True)
    await db.telegram_register_intents.create_index([("created_at", -1)])
    await db.telegram_tx_sessions.create_index([("chat_id", 1)], unique=True)
    await db.telegram_tx_sessions.create_index([("updated_at", -1)])


    
    
