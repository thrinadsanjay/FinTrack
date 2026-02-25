def delta_for_tx(tx_type: str, amount: float) -> float:
    return amount if tx_type == "credit" else -amount


def delta_for_delete(tx_type: str, amount: float) -> float:
    return -amount if tx_type == "credit" else amount


def delta_for_edit(tx_type: str, old_amount: float, new_amount: float) -> float:
    if tx_type == "credit":
        return new_amount - old_amount
    return old_amount - new_amount


async def apply_account_delta(*, db, account_id, delta: float) -> None:
    await db.accounts.update_one({"_id": account_id}, {"$inc": {"balance": delta}})


async def apply_transfer_deltas(*, db, source_account_id, target_account_id, amount: float) -> None:
    await db.accounts.update_one({"_id": source_account_id}, {"$inc": {"balance": -amount}})
    await db.accounts.update_one({"_id": target_account_id}, {"$inc": {"balance": amount}})
