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


@pytest.mark.asyncio
async def test_link_links_and_unlink_round_trip(tmp_path):
    loop = _loop(tmp_path)
    other = loop.sessions.get_or_create("cli:Other-1")  # the key keeps its case
    for i in range(4):
        other.add_message("user" if i % 2 == 0 else "assistant", f"other chat message {i}")
    loop.sessions.save(other)
    s = session(loop)
    for i in range(4):
        s.add_message("user" if i % 2 == 0 else "assistant", f"this chat message {i}")
    loop.sessions.save(s)

    assert "No links" in await run(loop, "links")
    reply = await run(loop, "link cli:Other-1#3")
    assert "Linked `cli:Other-1#3` into message 3" in reply
    assert session(loop).metadata["context_edges"] == [{"source": ["cli:Other-1", 3], "target": ["cli:c", 3]}]
    assert loop.sessions.read_session_snapshot("cli:c").metadata["context_edges"]  # saved

    listing = await run(loop, "links")
    assert "1." in listing and "cli:Other-1#3" in listing and "other chat message 3" in listing
    assert "this chat message 3" in listing

    assert "Linked `cli:Other-1#1` into message 2" in await run(loop, "link cli:Other-1#1 2")
    assert "Removed link 1" in await run(loop, "unlink 1")
    assert [e["source"] for e in session(loop).metadata["context_edges"]] == [["cli:Other-1", 1]]
    assert "Removed link 1" in await run(loop, "unlink 1")
    assert "No links" in await run(loop, "links") and "context_edges" not in session(loop).metadata


@pytest.mark.asyncio
async def test_bad_links_explain_themselves_and_change_nothing(tmp_path):
    loop = _loop(tmp_path)
    s = session(loop)
    s.add_message("user", "hello")
    loop.sessions.save(s)
    for args, needle in [
        ("link", "Usage: `/context link"),
        ("link nohash", "not a message id"),
        ("link cli:gone#0", "was not found"),
        ("link cli:c#0", "itself"),
        ("link cli:c#0 x", "Usage: `/context link"),
        ("unlink", "Usage: `/context unlink"),
        ("unlink 7", "no link number 7"),
        ("unlink x", "Usage: `/context unlink"),
    ]:
        assert needle in await run(loop, args), args
    assert "context_edges" not in session(loop).metadata


@pytest.mark.asyncio
async def test_context_help_mentions_the_link_commands(tmp_path):
    assert "/context link" in await run(_loop(tmp_path), "")
