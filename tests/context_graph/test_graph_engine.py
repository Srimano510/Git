from nanobot.context_graph.engines import GraphContextEngine
from nanobot.context_graph.store import ContextGraphStore
from nanobot.session import Session


def test_graph_engine_builds_context_and_syncs_graph(tmp_path):
    engine = GraphContextEngine()
    session = Session(
        key="test-graph",
        messages=[
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ],
    )
    store = ContextGraphStore(root=tmp_path)

    result = engine.build_context(session, store=store)

    assert result.strategy == "graph"
    assert [message["content"] for message in result.messages] == ["Question", "Answer"]
    assert len(result.node_ids) == 2
    assert result.diagnostics["total_graph_nodes"] == 2


def test_graph_engine_sync_is_idempotent(tmp_path):
    engine = GraphContextEngine()
    session = Session(
        key="test-graph-idempotent",
        messages=[{"role": "user", "content": "Question"}],
    )
    store = ContextGraphStore(root=tmp_path)

    first = engine.build_context(session, store=store)
    second = engine.build_context(session, store=store)

    assert second.node_ids == first.node_ids
    assert second.diagnostics["total_graph_nodes"] == first.diagnostics["total_graph_nodes"]
    assert second.diagnostics["branch_count"] == 0