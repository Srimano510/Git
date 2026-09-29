from nanobot.context_graph.model import (
    ChatNode,
    ConversationGraph,
    EdgeType,
)
from nanobot.context_graph.engines import GraphContextEngine, LinearContextEngine
from nanobot.context_graph.store import ContextGraphStore
from nanobot.context_graph.sync import GRAPH_ID_METADATA_KEY
from nanobot.session.manager import SessionManager


def make_node(
    graph: ConversationGraph,
    role: str,
    content: str,
    session: str,
    index: int,
):
    node = ChatNode.create(
        role=role,
        content=content,
        session_key=session,
        session_message_index=index,
    )

    graph.add_node(node)

    return node


def test_multiple_children_are_supported():
    graph = ConversationGraph()

    root = make_node(
        graph,
        "user",
        "Start project",
        "session-a",
        0,
    )

    child_a = make_node(
        graph,
        "assistant",
        "Use REST",
        "session-a",
        1,
    )

    child_b = make_node(
        graph,
        "user",
        "Use GraphQL instead",
        "session-b",
        1,
    )

    graph.add_edge(
        root.id,
        child_a.id,
        EdgeType.REPLY,
    )

    graph.add_edge(
        root.id,
        child_b.id,
        EdgeType.BRANCH,
    )

    children = graph.children(root.id)

    assert len(children) == 2

    assert graph.has_edge(
        root.id,
        child_a.id,
        EdgeType.REPLY,
    )

    assert graph.has_edge(
        root.id,
        child_b.id,
        EdgeType.BRANCH,
    )


def test_branch_edge_is_idempotent():
    graph = ConversationGraph()

    source = make_node(
        graph,
        "assistant",
        "Use REST",
        "parent",
        2,
    )

    child = make_node(
        graph,
        "user",
        "Actually use GraphQL",
        "child",
        2,
    )

    graph.add_branch(
        source.id,
        child.id,
    )

    graph.add_branch(
        source.id,
        child.id,
    )

    assert len(graph.branch_edges()) == 1


def test_multiple_branches_from_same_node():
    graph = ConversationGraph()

    source = make_node(
        graph,
        "assistant",
        "Choose an architecture",
        "parent",
        2,
    )

    child_one = make_node(
        graph,
        "user",
        "Use REST",
        "child-1",
        2,
    )

    child_two = make_node(
        graph,
        "user",
        "Use GraphQL",
        "child-2",
        2,
    )

    graph.add_branch(
        source.id,
        child_one.id,
    )

    graph.add_branch(
        source.id,
        child_two.id,
    )

    branches = [
        child
        for child in graph.children(
            source.id,
            EdgeType.BRANCH,
        )
    ]

    assert len(branches) == 2


def test_graph_round_trip_preserves_branch():
    graph = ConversationGraph()

    source = make_node(
        graph,
        "assistant",
        "Use REST",
        "parent",
        2,
    )

    child = make_node(
        graph,
        "user",
        "Use GraphQL",
        "child",
        2,
    )

    graph.add_branch(
        source.id,
        child.id,
    )

    data = graph.to_dict()

    restored = ConversationGraph.from_dict(data)

    assert restored.graph_id == graph.graph_id

    assert len(restored.nodes) == 2

    assert len(restored.branch_edges()) == 1

    edge = restored.branch_edges()[0]

    assert edge.source == source.id
    assert edge.target == child.id
    assert edge.type == EdgeType.BRANCH


def test_historical_fork_persists_branch_after_reloading_sessions_and_graph(tmp_path):
    sessions = SessionManager(
        tmp_path / "workspace",
        sessions_root=tmp_path / "session-files",
    )
    source = sessions.get_or_create("websocket:source")
    source.add_message("user", "Start project")
    source.add_message("assistant", "Use approach A")
    source.add_message("user", "A later question")
    source.add_message("assistant", "A later answer")
    sessions.save(source)

    child = sessions.fork_session_before_user_index(
        source.key,
        "websocket:child",
        1,
        include_user_message=True,
    )
    assert child is not None
    child.add_message("user", "Consider approach B")
    sessions.save(child)

    source_reload = sessions.read_session_snapshot(source.key)
    child_reload = sessions.read_session_snapshot(child.key)
    assert source_reload is not None
    assert child_reload is not None

    store = ContextGraphStore(root=tmp_path / "graphs")
    LinearContextEngine().build_context(source_reload, store=store)
    result = GraphContextEngine().build_context(child_reload, store=store)

    graph_id = child_reload.metadata[GRAPH_ID_METADATA_KEY]
    graph = store.load("sessions", graph_id)
    assert graph is not None

    source_boundary = graph.provenance_index[(source.key, 2)]
    child_divergence = graph.provenance_index[(child.key, 3)]
    assert graph.provenance_index[(child.key, 0)] == graph.provenance_index[(source.key, 0)]
    assert graph.provenance_index[(child.key, 2)] == source_boundary
    assert graph.has_edge(source_boundary, child_divergence, EdgeType.BRANCH)
    assert not graph.has_edge(source_boundary, child_divergence, EdgeType.REPLY)
    assert result.diagnostics["branches_added"] == 1
    assert result.diagnostics["branch_count"] == 1
    assert result.diagnostics["graph_sync_ms"] >= 0