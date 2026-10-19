import json

from nanobot.config.schema import ContextGraphConfig
from nanobot.context_graph import GraphContextEngine
from nanobot.context_graph.observatory import build_observatory
from nanobot.runtime_context import RUNTIME_CONTEXT_HISTORY_META
from nanobot.session import Session

QUERY = "Remind me which database the orders service uses"


def seeded(strategy="hybrid", at=None) -> Session:
    s = Session(key="cli:c")
    s.add_message("user", "Which database should the orders service use?")
    s.add_message("assistant", "Use Postgres for the orders database.")
    for i in range(6):
        s.add_message("user", f"fun fact request {i}")
        s.add_message("assistant", f"bananas are berries {i}")
    s.last_archived = 4
    s.metadata["_last_turn"] = {
        "strategy": strategy,
        "at": len(s.messages) if at is None else at,
        "max_tokens": 100_000,
        "graph_config": ContextGraphConfig().model_dump(),
    }
    s.add_message("user", QUERY)  # the turn itself and its reply happened after the snapshot
    s.add_message("assistant", "Postgres, as recalled.")
    return s


def observe(*sessions: Session, key=None):
    by_key = {s.key: s for s in sessions}
    return build_observatory(
        key or sessions[0].key, by_key.get, lambda: [{"key": k} for k in by_key]
    )


def ids(dto, strategy):
    return {n["id"] for n in dto["nodes"] if n["in"][strategy]}


def test_three_strategies_are_rebuilt_from_the_state_before_the_turn():
    dto = observe(seeded())
    assert dto["reconstructed"] is True and dto["selected"] == "hybrid" and dto["at"] == 14
    assert dto["query"] == QUERY
    assert set(dto["strategies"]) == {"linear", "graph", "hybrid"}
    everything = ids(dto, "linear") | ids(dto, "graph") | ids(dto, "hybrid")
    assert "cli:c#14" not in everything and "cli:c#15" not in everything  # query and reply

    # graph replays from the archive pointer; hybrid adds the archived Postgres answer back
    assert ids(dto, "graph") == {f"cli:c#{i}" for i in range(4, 14)}
    assert "cli:c#1" in ids(dto, "hybrid") and "cli:c#1" not in ids(dto, "graph")
    assert ids(dto, "graph") <= ids(dto, "linear")
    row = next(n for n in dto["nodes"] if n["id"] == "cli:c#1")
    assert row["reason"]["hybrid"].startswith("vector") and row["in"]["graph"] is False


def test_diff_counts_and_metrics():
    dto = observe(seeded())
    for name, s in dto["strategies"].items():
        assert s["nodes"] == len(ids(dto, name)) and s["tokens"] > 0
        assert s["fallback"] is None and s["ms"] >= 0
        assert set(s["timing"]) == {"traversal_ms", "vector_ms", "total_ms"}
    assert dto["strategies"]["linear"]["timing"]["vector_ms"] == 0
    assert dto["strategies"]["hybrid"]["recalled"] >= 1
    only_hybrid = [n for n in dto["nodes"] if n["in"] == {"linear": False, "graph": False, "hybrid": True}]
    assert dto["only"]["hybrid"] == len(only_hybrid) >= 1
    assert dto["only"]["graph"] == 0
    # hybrid tokens include the recalled block, so it costs more than plain graph here
    assert dto["strategies"]["hybrid"]["tokens"] > dto["strategies"]["graph"]["tokens"]


def test_linear_ids_skip_command_turns():
    s = Session(key="s")
    for role, text, extra in [
        ("user", "q0", {}), ("assistant", "a1", {}),
        ("user", "/context linear", {"_command": True}),
        ("assistant", "switched", {"_command": True}),
        ("user", "q4", {}), ("assistant", "a5", {}),
    ]:
        s.add_message(role, text, **extra)
    s.metadata["_last_turn"] = {"strategy": "linear", "at": 6, "max_tokens": 100_000, "graph_config": {}}
    s.add_message("user", "next")
    dto = observe(s)
    assert ids(dto, "linear") == {"s#0", "s#1", "s#4", "s#5"}


def test_a_failing_strategy_shows_its_fallback_and_the_others_still_return(monkeypatch):
    original = GraphContextEngine.build_context

    def flaky(self, session, **kw):
        if kw.get("hybrid"):
            raise RuntimeError("boom")
        return original(self, session, **kw)

    monkeypatch.setattr(GraphContextEngine, "build_context", flaky)
    dto = observe(seeded())
    assert dto["strategies"]["hybrid"]["fallback"] == "RuntimeError: boom"
    assert dto["strategies"]["hybrid"]["nodes"] == 0
    assert dto["strategies"]["graph"]["nodes"] == 10 and dto["strategies"]["graph"]["fallback"] is None
    assert dto["strategies"]["linear"]["nodes"] >= 10


def test_engine_level_fallback_is_visible(monkeypatch):
    def broken(*a, **k):
        raise LookupError("source gone")

    monkeypatch.setattr("nanobot.context_graph.engines.build_session_graph", broken)
    dto = observe(seeded("graph"))
    assert dto["strategies"]["graph"]["fallback"] == "LookupError: source gone"
    # the engine fell back to linear history: the card still counts what the model would get
    assert dto["strategies"]["graph"]["nodes"] > 0 and ids(dto, "graph") == set()
    assert dto["strategies"]["linear"]["fallback"] is None


def test_excerpts_are_truncated_and_runtime_context_is_removed():
    s = seeded()
    s.messages[6] = {
        "role": "user",
        "content": "visible request\n\nSECRET-RUNTIME-BLOCK",
        RUNTIME_CONTEXT_HISTORY_META: {"version": 1, "suffix": "SECRET-RUNTIME-BLOCK"},
    }
    s.messages[7] = {"role": "assistant", "content": "x" * 5000}
    dto = observe(s)
    blob = json.dumps(dto)
    assert "SECRET-RUNTIME-BLOCK" not in blob
    rows = {n["id"]: n for n in dto["nodes"]}
    assert rows["cli:c#6"]["excerpt"] == "visible request"
    assert len(rows["cli:c#7"]["excerpt"]) <= 121
    assert all(set(n) == {"id", "role", "excerpt", "tokens", "in", "reason"} for n in dto["nodes"])


def test_none_without_a_recorded_turn_or_anchor():
    s = seeded()
    del s.metadata["_last_turn"]
    assert observe(s) is None
    s = seeded()
    s.metadata["_last_turn"] = "garbage"
    assert observe(s) is None
    s = seeded()
    s.messages = s.messages[:14]  # the turn's user message is gone
    assert observe(s) is None
    assert build_observatory("missing", {}.get, lambda: []) is None


def test_each_chat_gets_only_its_own_nodes():
    a, b = seeded(), seeded()
    b.key = "cli:other"
    b.messages[0]["content"] = "other chat only text"
    dto = observe(a, b, key="cli:c")
    assert all(n["id"].startswith("cli:c#") for n in dto["nodes"])
    assert "other chat only text" not in json.dumps(dto)
    assert any(n["id"].startswith("cli:other#") for n in observe(a, b, key="cli:other")["nodes"])


def test_a_compacted_chat_followed_by_command_turns_compares_without_fallback():
    s = Session(key="cli:c")
    s.add_message("user", "Which database should the orders service use?")
    s.add_message("assistant", "Use Postgres for the orders database.")
    s.add_message("user", "/context hybrid", _command=True)
    s.add_message("assistant", "Switched context strategy to `hybrid`.", _command=True)
    s.last_archived = 2  # the real-world case: only command turns remain after the archive
    s.metadata["_last_turn"] = {
        "strategy": "hybrid", "at": 4, "max_tokens": 100_000,
        "graph_config": ContextGraphConfig().model_dump(),
    }
    s.add_message("user", "which database for the orders service")
    dto = observe(s)
    for name in ("graph", "hybrid"):
        assert dto["strategies"][name]["fallback"] is None
    assert dto["strategies"]["graph"]["nodes"] == 0  # nothing left to replay, and that is not an error
    assert ids(dto, "hybrid") == {"cli:c#0", "cli:c#1"}  # recall brings the archived exchange back
    assert ids(dto, "linear") == {"cli:c#0", "cli:c#1"}  # linear keeps a short archived tail


def test_budget_pruning_and_the_embedder_are_reported():
    s = Session(key="cli:c")
    for i in range(6):
        s.add_message("user", f"small talk number {i} about fruit")
        s.add_message("assistant", f"bananas are berries and tomatoes are fruit {i}")
    s.add_message("user", "Which database should the orders service use?")
    s.add_message("assistant", "We decided on Postgres as the database for the orders service.")
    for i in range(3):
        s.add_message("user", f"more small talk {i} about the weather")
        s.add_message("assistant", f"sunny with clouds {i}")
    s.metadata["_last_turn"] = {
        "strategy": "graph", "at": len(s.messages), "max_tokens": 100_000,
        "graph_config": ContextGraphConfig(
            graph_token_budget=120, keep_recent_turns=2, semantic_embedder="hash"
        ).model_dump(),
    }
    s.add_message("user", "which database did we pick for the orders service")
    dto = observe(s)
    graph, linear = dto["strategies"]["graph"], dto["strategies"]["linear"]
    assert graph["pruned"] > 0 and graph["embedder"] == "hash"
    assert graph["tokens"] < linear["tokens"] and graph["nodes"] < linear["nodes"]
    row = next(n for n in dto["nodes"] if n["id"] == "cli:c#13")  # the assistant's Postgres answer
    assert row["in"]["graph"] and row["reason"]["graph"].startswith("relevance (score ")
    assert linear.get("pruned", 0) == 0 and "embedder" not in linear
