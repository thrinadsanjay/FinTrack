"""Optional OpenAI narratives on top of authorized FinTracker tools."""

from __future__ import annotations

import json
import os
from typing import Any

from app.helpers.ai_client import log_ai_failure, openai_client
from app.helpers.ai_privacy import hallucination_guard_text
from app.helpers.monthly_review_math import build_monthly_review, explanation_facts, fallback_explanation
from app.helpers.recommendations import build_recommendations
from app.services import ai_tools
from app.services.chat_assistant import ai_available
from app.services.planning import build_planning_bundle

MAX_TOOL_ROUNDS = 4


def _model() -> str:
    return os.getenv("FT_OPENAI_MODEL") or "gpt-4o-mini"


async def ask_fintracker(*, user_id: str, question: str) -> dict:
    text = str(question or "").strip()
    if not text:
        return {"reply": "Ask a question about your finances.", "citations": [], "ai_available": ai_available()}
    if not ai_available():
        return {
            "reply": "Ask FinTracker is optional and needs an OpenAI API key. Planning pages still show calculated figures without AI.",
            "citations": [],
            "ai_available": False,
        }
    try:
        client = openai_client()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": ai_tools.system_prompt()},
            {"role": "user", "content": text[:2000]},
        ]
        citations: list[dict] = []
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = await client.chat.completions.create(
                model=_model(),
                messages=messages,
                tools=ai_tools.OPENAI_TOOLS,
                tool_choice="auto",
                temperature=0.1,
            )
            msg = response.choices[0].message
            tool_calls = msg.tool_calls or []
            if not tool_calls:
                reply = (msg.content or "").strip()
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for call in tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name not in ai_tools.tool_names():
                    result = json.dumps({"error": "tool_not_allowed"})
                else:
                    result = await ai_tools.execute_tool(user_id=user_id, name=name, arguments=args)
                    citations.append({"tool": name})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        if not reply:
            reply = "I could not complete that from the available FinTracker records."
        return {"reply": reply, "citations": citations[:8], "ai_available": True}
    except Exception as exc:
        log_ai_failure("Ask FinTracker", exc)
        return {
            "reply": "The assistant could not reach the language model. Your records were not changed.",
            "citations": [],
            "ai_available": ai_available(),
        }


async def explain_insight(*, user_id: str, insight: dict) -> dict:
    bundle = await build_planning_bundle(user_id, persist=False)
    facts = explanation_facts(insight=insight, category_changes=bundle.get("category_changes") or [])
    fallback = fallback_explanation(facts)
    if not ai_available():
        return {"explanation": fallback, "ai_available": False, "facts": facts}
    try:
        client = openai_client()
        prompt = (
            hallucination_guard_text()
            + " Explain the insight using ONLY this JSON. "
            "If the facts cannot establish a reason, say so clearly. "
            "Do not add merchants or amounts that are not in the JSON.\n"
            + json.dumps(facts, default=str)
        )
        response = await client.chat.completions.create(
            model=_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = (response.choices[0].message.content or "").strip() or fallback
        return {"explanation": text, "ai_available": True, "facts": facts}
    except Exception as exc:
        log_ai_failure("AI explanation", exc)
        return {"explanation": fallback, "ai_available": ai_available(), "facts": facts}


def review_from_bundle(bundle: dict) -> dict:
    """Deterministic monthly review numbers from an already-built planning bundle."""
    return build_monthly_review(
        {
            "today": bundle.get("today"),
            "month_income": bundle.get("month_income"),
            "month_expense": bundle.get("month_expense"),
            "prev_month_income": bundle.get("prev_month_income"),
            "prev_month_expense": bundle.get("prev_month_expense"),
            "savings_rate": bundle.get("savings_rate"),
            "insights": bundle.get("insights"),
            "category_changes": bundle.get("category_changes"),
            "credit_cards": bundle.get("credit_cards"),
            "goals": bundle.get("goals"),
            "upcoming": (bundle.get("calendar") or {}).get("upcoming") or [],
        }
    )


async def monthly_review(*, user_id: str, with_narrative: bool = True) -> dict:
    bundle = await build_planning_bundle(user_id, persist=False)
    report = review_from_bundle(bundle)
    if with_narrative and ai_available():
        try:
            client = openai_client()
            prompt = (
                "Write a short calm monthly review narrative. Do not change any numbers. "
                "Do not invent causes. Skip sections with null data. Not financial advice.\n"
                + json.dumps(
                    {
                        "month_label": report["month_label"],
                        "cash_flow": report["cash_flow"],
                        "highlights": report["highlights"],
                        "attention": report["attention"],
                        "category_changes": report["category_changes"],
                        "goals": report["goals"],
                    },
                    default=str,
                )
            )
            response = await client.chat.completions.create(
                model=_model(),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            report["narrative"] = (response.choices[0].message.content or "").strip() or None
        except Exception as exc:
            log_ai_failure("Monthly review narrative", exc)
            report["narrative"] = None
    report["ai_available"] = ai_available()
    return report


async def recommendations_for_user(user_id: str) -> list[dict]:
    bundle = await build_planning_bundle(user_id, persist=False)
    cards = bundle.get("credit_cards") or {}
    upcoming = (bundle.get("calendar") or {}).get("upcoming") or []
    from datetime import timedelta

    today = bundle.get("today")
    due_10 = 0
    if today:
        horizon = today + timedelta(days=10)
        for event in upcoming:
            day = event.get("date")
            try:
                if today <= day <= horizon:
                    due_10 += 1
            except TypeError:
                continue
    return build_recommendations(
        {
            "utilization": cards.get("overall_utilization"),
            "upcoming_due": cards.get("upcoming_due"),
            "payments_due_10_days": due_10,
            "category_changes": bundle.get("category_changes"),
            "goals_behind": [
                {"id": g.get("id"), "name": g.get("name"), "detail": g.get("eta_label")}
                for g in (bundle.get("goals") or [])
                if g.get("status") == "active" and g.get("on_track") is False
            ],
            "safe_to_spend": (bundle.get("safe_to_spend") or {}).get("safe_to_spend"),
            "cash": bundle.get("cash"),
            "reserved": (bundle.get("safe_to_spend") or {}).get("reserved"),
        }
    )
