import pytest

from nanobot.context_graph.derive import build_session_graph
from nanobot.context_graph.engines import GraphContextEngine
from nanobot.context_graph.model import EdgeType
from nanobot.context_graph.tree import node_to_fork_args
from nanobot.session.manager import SessionManager


def make_manager(tmp_path):
    return SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "session-files")


def seed_source(sessions):
    source = sessions.get_or_create("websocket:source")
    source.add_message("user", "Start project")
    source.add_message("assistant", "Use approach A")
    source.add_message("user", "A later question")
    source.add_message("assistant", "A later answer")
    sessions.save(source)
    return source


def fork_at(sessions, source, index, target="websocket:child"):
    before, include_user = node_to_fork_args(source.messages, index)
    return sessions.fork_session_before_user_index(
        source.key, target, before, include_user_message=include_user
    )


# P3.5-0: fork-at-node contract against the existing fork code.


def test_fork_at_mid_node_leaves_source_untouched(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed_source(sessions)
    child = fork_at(sessions, source, 1)
    child.add_message("user", "Consider approach B")
    sessions.save(child)

    assert [m["content"] for m in child.messages] == [
        "Start project",
        "Use approach A",
        "Consider approach B",
    ]
    reloaded = sessions.read_session_snapshot(source.key)
    assert [m["content"] for m in reloaded.messages] == [
        "Start project",
        "Use approach A",
        "A later question",
        "A later answer",
    ]


def test_fork_at_mid_node_adds_branch_edge_and_keeps_source_reply(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed_source(sessions)
    child = fork_at(sessions, source, 1)
    child.add_message("user", "Consider approach B")
    sessions.save(child)

    graph, _, _ = build_session_graph(child, sessions.read_session_snapshot)
    branch = [e for e in graph.edges if e.type is EdgeType.BRANCH]
    assert [(e.source, e.target) for e in branch] == [(("websocket:source", 1), (child.key, 2))]

    source_graph, _, _ = build_session_graph(source, sessions.read_session_snapshot)
    assert (("websocket:source", 1), ("websocket:source", 2)) in [
        (e.source, e.target) for e in source_graph.edges if e.type is EdgeType.REPLY
    ]


def test_child_graph_context_excludes_sibling_continuation(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed_source(sessions)
    child = fork_at(sessions, source, 1)
    child.add_message("user", "Consider approach B")
    sessions.save(child)

    result = GraphContextEngine(load_session=sessions.read_session_snapshot).build_context(
        sessions.read_session_snapshot(child.key)
    )
    contents = [m["content"] for m in result.messages]
    assert contents == ["Start project", "Use approach A", "Consider approach B"]


# P3.5-1: node -> fork-args mapping.

MESSAGES = [
    {"role": "user", "content": "q1"},
    {"role": "assistant", "content": "a1"},
    {"role": "user", "content": "q2"},
    {"role": "assistant", "content": "calling", "tool_calls": [{"id": "t"}]},
    {"role": "tool", "tool_call_id": "t", "content": "result"},
    {"role": "assistant", "content": "a2"},
]


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (0, (0, False)),  # first user message: re-ask from scratch
        (1, (1, False)),  # assistant reply keeps its turn
        (2, (1, False)),  # user node: re-ask, excludes q2
        (3, (2, False)),  # mid-turn assistant snaps to end of its turn
        (4, (2, False)),  # tool result snaps to end of its turn
        (5, (2, False)),  # tip: whole session prefix
    ],
)
def test_node_to_fork_args(index, expected):
    assert node_to_fork_args(MESSAGES, index) == expected


def test_hidden_user_message_snaps_to_turn_end():
    messages = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "hidden", "_hidden_history": True},
    ]
    from nanobot.session.history_visibility import is_hidden_history_message

    assert is_hidden_history_message(messages[2])
    assert node_to_fork_args(messages, 2) == (1, False)


@pytest.mark.parametrize("index", [-1, 6])
def test_node_to_fork_args_rejects_out_of_range(index):
    with pytest.raises(ValueError):
        node_to_fork_args(MESSAGES, index)
