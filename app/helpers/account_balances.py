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


def _balance_update(delta: float) -> list[dict]:
    # One pipeline update so the increment and 2dp rounding land atomically.
    return [
        {
            "$set": {
                "balance": {
                    "$round": [{"$add": [{"$ifNull": ["$balance", 0]}, delta]}, 2]
                }
            }
        }
    ]


async def apply_account_delta(
    *,
    db,
    account_id,
    delta: float,
    session=None,
    require_funds: bool = False,
) -> bool:
    """
    Atomically add delta to an account balance.

    With require_funds, a negative delta only applies if the balance covers it
    (check and debit in one write, so concurrent debits cannot overdraw).
    Returns False when the account is missing or funds are insufficient.
    """
    delta = round_money(delta)
    query: dict = {"_id": account_id}
    if require_funds and delta < 0:
        query["balance"] = {"$gte": -delta}
    result = await db.accounts.update_one(query, _balance_update(delta), session=session)
    return result.matched_count == 1


async def apply_transfer_deltas(
    *,
    db,
    source_account_id,
    target_account_id,
    amount: float,
    session=None,
    require_funds: bool = False,
) -> bool:
    """
    Move amount from source to target. Returns False (and changes nothing)
    when require_funds is set and the source cannot cover a positive amount.
    Without a session, the source debit is undone if the target credit fails.
    """
    amount = round_money(amount)
    debited = await apply_account_delta(
        db=db,
        account_id=source_account_id,
        delta=-amount,
        session=session,
        require_funds=require_funds,
    )
    if not debited:
        return False
    try:
        await apply_account_delta(db=db, account_id=target_account_id, delta=amount, session=session)
    except Exception:
        if session is None:
            await apply_account_delta(db=db, account_id=source_account_id, delta=amount)
        raise
    return True
