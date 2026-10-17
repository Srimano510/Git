from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.builtin import cmd_context
from nanobot.command.router import CommandContext
from nanobot.context_graph.summaries import list_summaries


def _loop(tmp_path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "m"
    return AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="m")


async def run(loop, args):
    msg = InboundMessage(channel="cli", sender_id="u", chat_id="c", content=f"/context {args}")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, args=args, loop=loop)
    return (await cmd_context(ctx)).content


def session(loop):
    return loop.sessions.get_or_create("cli:c")


@pytest.mark.asyncio
async def test_switches_between_strategies_including_hybrid(tmp_path):
    loop = _loop(tmp_path)
    for name in ("graph", "hybrid", "linear"):
        assert name in await run(loop, name)
        assert session(loop).metadata["context_strategy"] == name
    assert "Unknown context strategy" in await run(loop, "nope")
    assert "`hybrid`" in await run(loop, "")


@pytest.mark.asyncio
async def test_hybrid_pool_override_set_and_cleared(tmp_path):
    loop = _loop(tmp_path)
    assert "family" in await run(loop, "hybrid family")
    s = session(loop)
    assert (s.metadata["context_strategy"], s.metadata["context_pool"]) == ("hybrid", "family")
    await run(loop, "hybrid")  # no pool argument keeps the override
    assert session(loop).metadata["context_pool"] == "family"
    await run(loop, "hybrid default")
    assert "context_pool" not in session(loop).metadata
    assert "Unknown pool" in await run(loop, "hybrid everywhere")
    assert "context_pool" not in session(loop).metadata


@pytest.mark.asyncio
async def test_summary_commands_keep_the_original_text_case(tmp_path):
    loop = _loop(tmp_path)
    s = session(loop)
    for i in range(4):
        s.add_message("user" if i % 2 == 0 else "assistant", f"m{i}")
    loop.sessions.save(s)

    assert "No summaries" in await run(loop, "summary")
    assert "Saved" in await run(loop, "summary 0 2 We picked Postgres, NOT MySQL")
    assert list_summaries(session(loop)) == [{"from": 0, "to": 2, "text": "We picked Postgres, NOT MySQL"}]
    assert "0-2" in await run(loop, "summary")
    assert "Could not" in await run(loop, "summary 0 99 too far")
    assert "Could not" in await run(loop, "summary a b text")
    assert "Cleared 1" in await run(loop, "summary clear")
    assert list_summaries(session(loop)) == []
