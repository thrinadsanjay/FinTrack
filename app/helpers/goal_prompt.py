"""One-shot "link this investment to a goal?" prompt, carried across the post-save redirect.

Same mechanism as flash toasts: stored in the session by the controller that
saved the entry, popped (and rendered) by the next full page.
"""

from fastapi import Request

GOAL_PROMPT_KEY = "ft_goal_prompt"


def set_goal_prompt(request: Request | None, payload: dict | None) -> None:
    session = getattr(request, "session", None) if request is not None else None
    if session is None or not payload:
        return
    session[GOAL_PROMPT_KEY] = payload


def pop_goal_prompt(request: Request | None) -> dict | None:
    session = getattr(request, "session", None) if request is not None else None
    if session is None:
        return None
    data = session.pop(GOAL_PROMPT_KEY, None)
    if not isinstance(data, dict) or not (data.get("goals") or data.get("account_goals")):
        return None
    if not (data.get("transaction_id") or data.get("recurring_id")):
        return None
    return data
