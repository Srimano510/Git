"""Unit tests for Linear and Graph Context Engines."""

from pathlib import Path

from nanobot.context_graph.engines import (
    GraphContextEngine,
    LinearContextEngine,
    get_context_engine,
)
from nanobot.context_graph.store import ContextGraphStore
from nanobot.session.manager import Session


def test_linear_context_engine_retrieval(tmp_path: Path):
    session = Session(
        key="websocket:test-linear",
        messages=[
            {"role": "user", "content": "Msg 1"},
            {"role": "assistant", "content": "Msg 2"},
            {"role": "user", "content": "Msg 3"},
            {"role": "assistant", "content": "Msg 4"},
        ],
    )
    store = ContextGraphStore(root_dir=tmp_path)
    engine = LinearContextEngine(window_size=2)
    result = engine.build_context(session, store=store)

    assert result.strategy == "linear"
    assert len(result.messages) == 2
    assert result.messages[0]["content"] == "Msg 3"
    assert result.messages[1]["content"] == "Msg 4"
    assert result.token_count > 0
    assert result.retrieval_ms >= 0


def test_graph_context_engine_phase1_delegation(tmp_path: Path):
    session = Session(
        key="websocket:test-graph",
        messages=[
            {"role": "user", "content": "Question A"},
            {"role": "assistant", "content": "Answer A"},
        ],
    )
    store = ContextGraphStore(root_dir=tmp_path)
    engine = GraphContextEngine()
    result = engine.build_context(session, store=store)

    assert result.strategy == "graph"
    assert len(result.messages) == 2
    assert result.messages[0]["content"] == "Question A"
    assert result.messages[1]["content"] == "Answer A"
    assert len(result.node_ids) == 2
    assert result.diagnostics["phase"] == 1


def test_get_context_engine_factory():
    linear_engine = get_context_engine("linear")
    assert isinstance(linear_engine, LinearContextEngine)

    graph_engine = get_context_engine("graph")
    assert isinstance(graph_engine, GraphContextEngine)

    fallback_engine = get_context_engine("unknown_strategy")
    assert isinstance(fallback_engine, LinearContextEngine)
