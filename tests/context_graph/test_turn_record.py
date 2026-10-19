from unittest.mock import MagicMock

from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ContextGraphConfig
from nanobot.context_graph.tree import turn_anchor
from nanobot.session import Session
from nanobot.session.manager import SessionManager

QUERY = "Remind me which database the orders service uses"


def make_loop(tmp_path, **kw) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "m"
    return AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path, model="m",
        context_window_tokens=100_000, **kw,
    )


def session_with(strategy: str | None) -> Session:
    s = Session(key="cli:c")
    s.add_message("user", "Which database should the orders service use?")
    s.add_message("assistant", "Use Postgres for the orders database.")
    if strategy:
        s.metadata["context_strategy"] = strategy
    return s


def test_every_strategy_records_the_turn_for_the_observatory(tmp_path):
    loop = make_loop(tmp_path, context_graph_config=ContextGraphConfig(semantic_top_k=5))
    for strategy, expected in (
        (None, "linear"), ("linear", "linear"), ("graph", "graph"),
        ("context_graph", "graph"), ("hybrid", "hybrid"),
    ):
        s = session_with(strategy)
        history, result = loop._turn_history(s, QUERY, is_subagent=False)
        turn = s.metadata["_last_turn"]
        assert turn["strategy"] == expected and turn["at"] == 2
        assert turn["max_tokens"] == 100_000
        assert ContextGraphConfig.model_validate(turn["graph_config"]).semantic_top_k == 5
        assert [m["content"] for m in history] == [
            "Which database should the orders service use?",
            "Use Postgres for the orders database.",
        ]
        assert (result is None) == (expected == "linear")


def test_subagent_turns_record_nothing(tmp_path):
    s = session_with("graph")
    make_loop(tmp_path)._turn_history(s, "done", is_subagent=True)
    assert "_last_turn" not in s.metadata


def test_one_metrics_line_per_turn_for_each_strategy(tmp_path):
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        loop = make_loop(tmp_path)
        for strategy in ("linear", "graph", "hybrid"):
            loop._turn_history(session_with(strategy), QUERY, is_subagent=False)
    finally:
        logger.remove(sink)
    ctx = [m for m in lines if m.startswith("Context strategy=")]
    assert [m.split()[1] for m in ctx] == ["strategy=linear", "strategy=graph", "strategy=hybrid"]
    assert all("nodes=2" in m and "tokens=" in m and "ms=" in m for m in ctx)
    assert "recall=" in ctx[2] and "recall=" not in ctx[0]


def test_forks_do_not_inherit_the_last_turn(tmp_path):
    m = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    src = m.get_or_create("websocket:src")
    src.add_message("user", "q")
    src.add_message("assistant", "a")
    src.metadata["_last_turn"] = {"strategy": "graph", "at": 0}
    m.save(src)
    kid = m.fork_session_before_user_index(src.key, "websocket:kid", 1)
    assert "_last_turn" not in kid.metadata


def test_turn_anchor_is_the_first_visible_user_message_at_or_after_at():
    s = Session(key="s")
    s.add_message("user", "old")
    s.add_message("assistant", "old answer")
    s.add_message("user", "/context linear", _command=True)
    s.add_message("user", "the turn")
    assert turn_anchor(s, 2) == "s#3"
    assert turn_anchor(s, 0) == "s#0"
    assert turn_anchor(s, 99) is None


def test_graph_budget_reaches_the_turn_and_the_recorded_config(tmp_path):
    loop = make_loop(tmp_path, context_graph_config=ContextGraphConfig(
        graph_token_budget=60, keep_recent_turns=1, semantic_embedder="hash"))
    s = Session(key="cli:c")
    s.metadata["context_strategy"] = "graph"
    for i in range(8):
        s.add_message("user", f"unrelated small talk number {i} about fruit and weather")
        s.add_message("assistant", f"bananas are berries and tomatoes are fruit {i}")
    history, result = loop._turn_history(s, "unrelated small talk", is_subagent=False)
    assert result is not None and result.diagnostics["graph_budget"] == 60
    assert result.diagnostics["pruned_by_relevance"] > 0 and len(history) < 16
    recorded = s.metadata["_last_turn"]["graph_config"]
    assert recorded["graph_token_budget"] == 60 and recorded["keep_recent_turns"] == 1
