"""The AI flows must await the async OpenAI client (never block the event loop)."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import ai_finance


def _completion(*, content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class TestAskFinTrackerAsync(unittest.IsolatedAsyncioTestCase):
    async def test_tool_round_then_answer_is_awaited(self):
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="get_balance", arguments="{}"),
        )
        create = AsyncMock(
            side_effect=[
                _completion(content="", tool_calls=[tool_call]),
                _completion(content="You have 100 in cash."),
            ]
        )
        client = MagicMock()
        client.chat.completions.create = create

        with patch.object(ai_finance, "openai_client", return_value=client), \
             patch.object(ai_finance, "ai_available", return_value=True), \
             patch.object(ai_finance.ai_tools, "execute_tool", new=AsyncMock(return_value='{"cash": 100}')):
            result = await ai_finance.ask_fintracker(user_id="u1", question="How much cash?")

        self.assertEqual(result["reply"], "You have 100 in cash.")
        self.assertEqual(result["citations"], [{"tool": "get_balance"}])
        self.assertEqual(create.await_count, 2)


if __name__ == "__main__":
    unittest.main()
