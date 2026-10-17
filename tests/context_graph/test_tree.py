from nanobot.context_graph.tree import build_tree_graph
from nanobot.session.manager import SessionManager


def make_manager(tmp_path):
    return SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "session-files")


def seed(sessions):
    source = sessions.get_or_create("websocket:source")
    source.add_message("user", "Start project")
    source.add_message("assistant", "Use approach A")
    source.add_message("user", "A later question")
    source.add_message("assistant", "A later answer")
    sessions.save(source)
    return source


def fork(sessions, source_key, target, before, include=False):
    child = sessions.fork_session_before_user_index(
        source_key, target, before, include_user_message=include
    )
    return child


def tree(sessions, key):
    return build_tree_graph(key, sessions.list_sessions(), sessions.read_session_snapshot)


def edge_set(result, kind=None):
    return {
        (e["source"], e["target"])
        for e in result["edges"]
        if kind is None or e["type"] == kind
    }


def test_single_session_is_a_chain():
    # no manager needed: loader returns the one session
    from nanobot.session import Session

    s = Session(
        key="websocket:solo",
        messages=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
    )
    result = build_tree_graph("websocket:solo", [{"key": "websocket:solo"}], lambda k: s)
    assert [n["id"] for n in result["nodes"]] == ["websocket:solo#0", "websocket:solo#1"]
    assert edge_set(result) == {("websocket:solo#0", "websocket:solo#1")}
    assert result["tips"] == {"websocket:solo": "websocket:solo#1"}
    assert result["nodes"][0]["role"] == "user"
    assert result["nodes"][0]["preview"] == "q"


def test_family_includes_siblings_and_descendants_from_any_member(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed(sessions)
    a = fork(sessions, source.key, "websocket:a", 1)  # copies Start project + Use approach A
    a.add_message("user", "B question")
    sessions.save(a)
    b = fork(sessions, source.key, "websocket:b", 1)
    b.add_message("user", "C question")
    sessions.save(b)
    grand = fork(sessions, a.key, "websocket:grand", 2, include=True)
    grand.add_message("assistant", "deep")
    sessions.save(grand)

    from_grand = tree(sessions, "websocket:grand")
    from_source = tree(sessions, "websocket:source")

    assert from_grand == from_source
    ids = {n["id"] for n in from_source["nodes"]}
    # copied prefixes alias the source nodes: no duplicates of "Start project"
    assert "websocket:a#0" not in ids and "websocket:b#1" not in ids
    assert {"websocket:source#3", "websocket:a#2", "websocket:b#2"} <= ids
    assert set(from_source["tips"]) == {
        "websocket:source",
        "websocket:a",
        "websocket:b",
        "websocket:grand",
    }
    assert edge_set(from_source, "BRANCH") >= {
        ("websocket:source#1", "websocket:a#2"),
        ("websocket:source#1", "websocket:b#2"),
    }


def test_unrelated_sessions_are_excluded(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed(sessions)
    other = sessions.get_or_create("websocket:other")
    other.add_message("user", "unrelated")
    sessions.save(other)

    result = tree(sessions, source.key)
    assert set(result["tips"]) == {"websocket:source"}


def test_missing_source_session_still_returns_the_child_chain(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed(sessions)
    child = fork(sessions, source.key, "websocket:child", 1)
    child.add_message("user", "after")
    sessions.save(child)
    sessions.delete_session(source.key)

    result = tree(sessions, child.key)
    assert set(result["tips"]) == {"websocket:child"}
    assert any(n["id"] == "websocket:child#2" for n in result["nodes"])


def test_unknown_key_returns_none(tmp_path):
    sessions = make_manager(tmp_path)
    assert tree(sessions, "websocket:nope") is None


def test_preview_is_truncated_and_handles_blocks():
    from nanobot.session import Session

    s = Session(
        key="websocket:p",
        messages=[
            {"role": "user", "content": "x" * 300},
            {"role": "assistant", "content": [{"type": "text", "text": "block text"}]},
        ],
    )
    result = build_tree_graph("websocket:p", [{"key": "websocket:p"}], lambda k: s)
    assert len(result["nodes"][0]["preview"]) <= 81
    assert result["nodes"][1]["preview"] == "block text"


def test_nodes_carry_fork_args_and_user_text(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed(sessions)
    nodes = {n["id"]: n for n in tree(sessions, source.key)["nodes"]}

    assert nodes["websocket:source#0"]["fork_before_user_index"] == 0
    assert nodes["websocket:source#0"]["text"] == "Start project"
    assert nodes["websocket:source#1"]["fork_before_user_index"] == 1
    assert "text" not in nodes["websocket:source#1"]
    assert nodes["websocket:source#2"]["fork_before_user_index"] == 1
    assert nodes["websocket:source#3"]["fork_before_user_index"] == 2


def test_context_field_reports_last_turn_node_kinds_only_when_present(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed(sessions)
    assert "context" not in tree(sessions, source.key)

    source.metadata["_last_context"] = {
        "strategy": "hybrid",
        "nodes": {"websocket:source#3": "history", "websocket:source#0": "vector"},
    }
    sessions.save(source)
    result = tree(sessions, source.key)
    assert result["context"] == {"websocket:source#3": "history", "websocket:source#0": "vector"}
    assert result["context_strategy"] == "hybrid"

    source.metadata["_last_context"] = "garbage"
    sessions.save(source)
    assert "context" not in tree(sessions, source.key)


def test_slash_command_turns_are_left_out_and_the_chain_is_bridged(tmp_path):
    sessions = make_manager(tmp_path)
    s = sessions.get_or_create("websocket:cmd")
    s.add_message("user", "first question")
    s.add_message("assistant", "first answer")
    s.add_message("user", "/context hybrid", _command=True)
    s.add_message("assistant", "Switched context strategy to `hybrid`.", _command=True)
    s.add_message("user", "second question")
    s.add_message("assistant", "second answer")
    sessions.save(s)

    result = tree(sessions, s.key)
    ids = [n["id"] for n in result["nodes"]]
    assert ids == [f"websocket:cmd#{i}" for i in (0, 1, 4, 5)]
    assert edge_set(result) == {
        ("websocket:cmd#0", "websocket:cmd#1"),
        ("websocket:cmd#1", "websocket:cmd#4"),
        ("websocket:cmd#4", "websocket:cmd#5"),
    }
    assert result["tips"] == {"websocket:cmd": "websocket:cmd#5"}
