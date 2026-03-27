from app.helpers.money import round_money


def delta_for_tx(tx_type: str, amount: float) -> float:
    amount = round_money(amount)
    return round_money(amount if tx_type == "credit" else -amount)


def delta_for_delete(tx_type: str, amount: float) -> float:
    amount = round_money(amount)
    return round_money(-amount if tx_type == "credit" else amount)


def delta_for_edit(tx_type: str, old_amount: float, new_amount: float) -> float:
    old_amount = round_money(old_amount)
    new_amount = round_money(new_amount)
    if tx_type == "credit":
        return round_money(new_amount - old_amount)
    return round_money(old_amount - new_amount)


async def apply_account_delta(*, db, account_id, delta: float) -> None:
    delta = round_money(delta)
    await db.accounts.update_one({"_id": account_id}, {"$inc": {"balance": delta}})
    await db.accounts.update_one(
        {"_id": account_id},
        [{"$set": {"balance": {"$round": ["$balance", 2]}}}],
    )


async def apply_transfer_deltas(*, db, source_account_id, target_account_id, amount: float) -> None:
    amount = round_money(amount)
    await db.accounts.update_one({"_id": source_account_id}, {"$inc": {"balance": -amount}})
    await db.accounts.update_one({"_id": target_account_id}, {"$inc": {"balance": amount}})
    await db.accounts.update_one(
        {"_id": source_account_id},
        [{"$set": {"balance": {"$round": ["$balance", 2]}}}],
    )
    await db.accounts.update_one(
        {"_id": target_account_id},
        [{"$set": {"balance": {"$round": ["$balance", 2]}}}],
    )
