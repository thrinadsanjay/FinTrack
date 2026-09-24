def tx_failed_insufficient_payload(
    *,
    failed_id: str,
    is_transfer: bool,
    account_name: str,
    balance: float,
    amount: float,
) -> dict:
    return {
        "key": f"tx_failed:{failed_id}",
        "notif_type": "warning",
        "title": "Transfer failed: insufficient funds" if is_transfer else "Transaction failed: insufficient funds",
        "message": f"{account_name} has ₹ {balance}, but ₹ {amount} is required.",
    }


def tx_added_payload(*, tx_id: str, tx_type: str, amount: float) -> dict:
    return {
        "key": f"tx_added:{tx_id}",
        "notif_type": "success",
        "title": "Transfer added successfully" if tx_type == "transfer" else "Transaction added successfully",
        "message": f"₹ {amount} has been recorded.",
    }


def tx_deleted_payload(*, transaction_id: str, stamp: str, amount: float) -> dict:
    return {
        "key": f"tx_deleted:{transaction_id}:{stamp}",
        "notif_type": "success",
        "title": "Transaction deleted",
        "message": f"Deleted transaction of ₹ {amount}.",
    }


def tx_restored_payload(*, transaction_id: str, stamp: str, amount: float) -> dict:
    return {
        "key": f"tx_restored:{transaction_id}:{stamp}",
        "notif_type": "success",
        "title": "Transaction restored",
        "message": f"Restored transaction of ₹ {amount}.",
    }


def tx_updated_payload(*, transaction_id: str, stamp: str, new_amount: float) -> dict:
    return {
        "key": f"tx_edited:{transaction_id}:{stamp}",
        "notif_type": "success",
        "title": "Transaction updated",
        "message": f"Updated transaction to ₹ {new_amount}.",
    }


def retry_failed_payload(*, failed_id: str, account_name: str, balance: float, amount: float) -> dict:
    return {
        "key": f"failed_tx_retry_failed:{failed_id}",
        "notif_type": "warning",
        "title": "Retry failed: insufficient funds",
        "message": f"{account_name} has ₹ {balance}, but ₹ {amount} is required.",
    }


def retry_success_payload(*, failed_id: str, description: str, amount: float) -> dict:
    return {
        "key": f"failed_tx_retry_success:{failed_id}",
        "notif_type": "success",
        "title": "Retry successful",
        "message": f"{description} for ₹ {amount} was posted successfully.",
    }


def recurring_created_payload(*, recurring_id: str, stamp: str, tx_type: str, amount: float) -> dict:
    return {
        "key": f"recurring_created:{recurring_id}:{stamp}",
        "notif_type": "success",
        "title": "Recurring rule created",
        "message": f"Created recurring {tx_type} of ₹ {amount}.",
    }


def recurring_updated_payload(
    *, recurring_id: str, stamp: str, amount: float, frequency: str
) -> dict:
    return {
        "key": f"recurring_updated:{recurring_id}:{stamp}",
        "notif_type": "success",
        "title": "Recurring rule updated",
        "message": f"Updated recurring rule to ₹ {amount} ({frequency}).",
    }


def recurring_paused_payload(*, recurring_id: str, stamp: str, description: str) -> dict:
    return {
        "key": f"recurring_paused:{recurring_id}:{stamp}",
        "notif_type": "info",
        "title": "Recurring rule paused",
        "message": f"Paused recurring rule: {description}.",
    }


def recurring_resumed_payload(
    *, recurring_id: str, stamp: str, description: str, next_run_label: str
) -> dict:
    return {
        "key": f"recurring_resumed:{recurring_id}:{stamp}",
        "notif_type": "success",
        "title": "Recurring rule resumed",
        "message": f"Resumed recurring rule: {description} (next run {next_run_label}).",
    }


def recurring_ended_payload(*, recurring_id: str, stamp: str, description: str) -> dict:
    return {
        "key": f"recurring_ended:{recurring_id}:{stamp}",
        "notif_type": "info",
        "title": "Recurring rule ended",
        "message": f"Ended recurring rule: {description}.",
    }


def recurring_failed_scheduler_payload(
    *,
    recurring_id: str,
    schedule_key: str,
    account_name: str,
    balance: float,
    amount: float,
    description: str,
) -> dict:
    return {
        "key": f"recurring_failed:{recurring_id}:{schedule_key}",
        "notif_type": "warning",
        "title": "Recurring transaction failed",
        "message": (
            f"{account_name} has ₹ {balance}, but ₹ {amount} is required for {description}."
        ),
    }


def account_created_payload(*, account_id: str, name: str, acc_type: str) -> dict:
    labels = {
        "bank": "Account",
        "credit_card": "Credit card",
        "loan": "Loan",
    }
    kind = labels.get(acc_type, "Account")
    return {
        "key": f"account_created:{account_id}",
        "notif_type": "success",
        "title": f"{kind} added",
        "message": f"{name} was added to your accounts.",
    }


def account_updated_payload(*, account_id: str, stamp: str, name: str) -> dict:
    return {
        "key": f"account_updated:{account_id}:{stamp}",
        "notif_type": "success",
        "title": "Account updated",
        "message": f"{name} was updated.",
    }


def account_deleted_payload(*, account_id: str, stamp: str, name: str) -> dict:
    return {
        "key": f"account_deleted:{account_id}:{stamp}",
        "notif_type": "info",
        "title": "Account deleted",
        "message": f"{name} was deleted.",
    }
