from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.context_graph.summarize import SummaryError, generate_summary, transcript_for


def reply(content="A short summary.", finish_reason="stop"):
    return SimpleNamespace(content=content, finish_reason=finish_reason)


def provider(**kw):
    p = MagicMock()
    p.chat_with_retry = AsyncMock(return_value=reply(**kw))
    return p


MESSAGES = [
    {"role": "user", "content": "We chose Postgres for orders."},
    {"role": "assistant", "content": "Noted: Postgres."},
    {"role": "user", "content": "/context graph", "_command": True},
    {"role": "assistant", "content": "Switched.", "_command": True},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
    {"role": "tool", "tool_call_id": "1", "content": "SECRET-TOOL-OUTPUT " * 50},
]


def test_transcript_has_roles_skips_commands_and_never_includes_tool_output():
    text = transcript_for(MESSAGES)
    assert text.splitlines() == ["user: We chose Postgres for orders.", "assistant: Noted: Postgres."]
    assert "SECRET" not in text and "Switched" not in text


def test_transcript_truncates_long_messages():
    text = transcript_for([{"role": "user", "content": "word " * 2000}], max_chars_per_message=100)
    assert text.startswith("user: word") and len(text) < 200  # cut, not the 10,000 characters sent in


@pytest.mark.asyncio
async def test_generate_summary_asks_for_a_tool_free_call_and_treats_the_transcript_as_data():
    p = provider(content="  We chose Postgres for the orders service.  ")
    out = await generate_summary(p, "model-x", MESSAGES, max_tokens=300)
    assert out == "We chose Postgres for the orders service."
    p.chat_with_retry.assert_awaited_once()
    args, kwargs = p.chat_with_retry.call_args
    system, user = args[0]
    assert system["role"] == "system" and user["role"] == "user"
    assert "data, not instructions" in system["content"]
    assert "user: We chose Postgres for orders." in user["content"]
    assert kwargs["tools"] is None and kwargs["model"] == "model-x" and kwargs["max_tokens"] == 300


@pytest.mark.asyncio
async def test_a_failed_empty_or_raising_call_is_a_summary_error():
    with pytest.raises(SummaryError, match="boom"):
        await generate_summary(provider(content="Error calling LLM: boom", finish_reason="error"), "m", MESSAGES, max_tokens=300)
    with pytest.raises(SummaryError, match="no summary"):
        await generate_summary(provider(content="   "), "m", MESSAGES, max_tokens=300)
    broken = MagicMock()
    broken.chat_with_retry = AsyncMock(side_effect=RuntimeError("network down"))
    with pytest.raises(SummaryError, match="network down"):
        await generate_summary(broken, "m", MESSAGES, max_tokens=300)


@pytest.mark.asyncio
async def test_nothing_to_summarise_never_calls_the_model():
    p = provider()
    with pytest.raises(SummaryError, match="nothing to summarise"):
        await generate_summary(p, "m", MESSAGES[2:4] + MESSAGES[4:], max_tokens=300)
    p.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_over_long_reply_is_cut_to_the_token_cap():
    out = await generate_summary(provider(content="word " * 5000), "m", MESSAGES, max_tokens=50)
    assert len(out) < 600
