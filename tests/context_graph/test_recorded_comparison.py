import json
from unittest.mock import MagicMock

import pytest
from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ContextGraphConfig
from nanobot.context_graph import observatory
from nanobot.context_graph.observatory import MAX_NODES, build_observatory
from nanobot.session import Session
from nanobot.utils.helpers import estimate_message_tokens

QUERY = "Remind me which database the orders service uses"


def make_loop(tmp_path, **cfg) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "m"
    return AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path, model="m",
        context_window_tokens=100_000,
        context_graph_config=ContextGraphConfig(semantic_embedder="hash", **cfg),
    )


def archived_session(strategy="hybrid", key="cli:c") -> Session:
    s = Session(key=key)
    s.add_message("user", "Which database should the orders service use?")
    s.add_message("assistant", "Use Postgres for the orders database.")
    for i in range(6):
        s.add_message("user", f"fun fact request {i}")
        s.add_message("assistant", f"bananas are berries {i}")
    s.last_archived = 4
    s.metadata["context_strategy"] = strategy
    return s


def observe(loop, s: Session):
    """What the route does: the saved session in, the Observatory payload out."""
    loop.sessions.save(s)
    s.add_message("user", QUERY)  # the user message is persisted after the context is built
    loop.sessions.save(s)
    return build_observatory(s.key, loop.sessions.read_session_snapshot, loop.sessions.list_sessions)


@pytest.mark.parametrize("strategy", ["linear", "graph", "hybrid"])
def test_the_selected_strategy_is_recorded_with_the_real_numbers(tmp_path, strategy):
    loop = make_loop(tmp_path)
    s = archived_session(strategy)
    history, result = loop._turn_history(s, QUERY, is_subagent=False)
    comparison = s.metadata["_last_turn"]["comparison"]

    assert comparison["reconstructed"] is False and comparison["selected"] == strategy
    assert comparison["at"] == len(s.messages) and comparison["query"] == QUERY
    real = comparison["strategies"][strategy]
    assert real["nodes"] == (len(result.node_ids) if result else len(history))
    expected_tokens = (
        result.token_count + (estimate_message_tokens({"content": result.recalled}) if result.recalled else 0)
        if result else sum(estimate_message_tokens(m) for m in history)
    )
    assert real["tokens"] == expected_tokens
    assert set(comparison["strategies"]) == {"linear", "graph", "hybrid"}  # the other two are there too
    json.dumps(comparison)  # JSON-safe: it is stored in the session file


def test_flag_off_records_nothing_and_the_observatory_rebuilds(tmp_path):
    loop = make_loop(tmp_path, record_comparison=False)
    s = archived_session()
    loop._turn_history(s, QUERY, is_subagent=False)
    assert "comparison" not in s.metadata["_last_turn"]
    assert observe(loop, s)["reconstructed"] is True


def test_a_failure_while_recording_never_breaks_the_turn(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("compare exploded")

    monkeypatch.setattr(observatory, "compare", boom)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="WARNING")
    try:
        history, _ = make_loop(tmp_path)._turn_history(s := archived_session(), QUERY, is_subagent=False)
    finally:
        logger.remove(sink)
    assert history  # the turn got its context
    assert "comparison" not in s.metadata["_last_turn"]
    assert any("comparison" in m.lower() and "compare exploded" in m for m in lines)


def test_subagent_turns_record_no_comparison(tmp_path):
    s = archived_session()
    make_loop(tmp_path)._turn_history(s, "done", is_subagent=True)
    assert "_last_turn" not in s.metadata


def test_the_recorded_comparison_stays_exact_after_compaction(tmp_path):
    loop = make_loop(tmp_path)
    s = archived_session()
    loop._turn_history(s, QUERY, is_subagent=False)
    recorded = observe(loop, s)
    assert recorded["reconstructed"] is False

    s.last_archived = len(s.messages)  # the chat was compacted after the turn
    loop.sessions.save(s)
    after = build_observatory(s.key, loop.sessions.read_session_snapshot, loop.sessions.list_sessions)
    assert after == recorded  # recorded numbers do not drift

    del s.metadata["_last_turn"]["comparison"]  # whereas a rebuild now sees an empty replay
    loop.sessions.save(s)
    rebuilt = build_observatory(s.key, loop.sessions.read_session_snapshot, loop.sessions.list_sessions)
    assert rebuilt["reconstructed"] is True and rebuilt["strategies"]["graph"]["nodes"] == 0
    assert recorded["strategies"]["graph"]["nodes"] > 0


def test_a_stale_or_broken_recording_falls_back_to_a_rebuild(tmp_path):
    loop = make_loop(tmp_path)
    s = archived_session()
    loop._turn_history(s, QUERY, is_subagent=False)
    s.metadata["_last_turn"]["comparison"]["at"] = 999  # does not belong to this turn
    assert observe(loop, s)["reconstructed"] is True
    s.metadata["_last_turn"]["comparison"] = "garbage"
    loop.sessions.save(s)
    assert build_observatory(s.key, loop.sessions.read_session_snapshot, loop.sessions.list_sessions)["reconstructed"] is True


def test_the_stored_node_list_is_capped_but_the_counts_stay_exact(tmp_path):
    from nanobot.context_graph.observatory import compare

    loop = make_loop(tmp_path)
    s = Session(key="cli:big")
    for i in range(MAX_NODES + 60):
        s.add_message("user" if i % 2 == 0 else "assistant", f"message number {i} about nothing")
    s.last_archived = 20  # graph starts at 20 while linear keeps a short archived tail: some nodes differ
    record = {"strategy": "graph", "at": len(s.messages), "max_tokens": 100_000,
              "graph_config": loop.context_graph_config.model_dump()}
    load, listing = loop.sessions.read_session_snapshot, loop.sessions.list_sessions

    full = compare(s, "message number 3 about nothing", record, load, listing, max_nodes=10**6)
    capped = compare(s, "message number 3 about nothing", record, load, listing, max_nodes=MAX_NODES)

    assert full["omitted"] == 0 and len(full["nodes"]) > MAX_NODES
    assert len(capped["nodes"]) == MAX_NODES
    assert capped["omitted"] == len(full["nodes"]) - MAX_NODES
    for name in ("linear", "graph", "hybrid"):  # counts and tokens cover every node, listed or not
        for field in ("nodes", "tokens"):
            assert capped["strategies"][name][field] == full["strategies"][name][field]
    assert capped["only"] == full["only"]

    differing = {n["id"] for n in full["nodes"] if len(set(n["in"].values())) > 1}
    assert differing and differing <= {n["id"] for n in capped["nodes"]}  # differences are kept first
    ids = [n["id"] for n in capped["nodes"]]
    assert ids == sorted(ids, key=lambda x: (x.rpartition("#")[0], int(x.rpartition("#")[2])))
