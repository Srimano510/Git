from nanobot.context_graph.engines import GraphContextEngine
from nanobot.session import Session
from nanobot.session.manager import SessionManager


def make_manager(tmp_path):
    return SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "session-files")


def texts(result):
    return [m["content"] for m in result.messages]


def seed_source(sessions):
    source = sessions.get_or_create("websocket:source")
    source.add_message("user", "Start project")
    source.add_message("assistant", "Use approach A")
    source.add_message("user", "A later question")
    source.add_message("assistant", "A later answer")
    sessions.save(source)
    return source


def test_single_session_matches_linear_history():
    session = Session(
        key="s",
        messages=[
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ],
    )

    result = GraphContextEngine().build_context(session)

    assert result.strategy == "graph"
    assert texts(result) == ["Question", "Answer"]
    assert result.node_ids == ["s#0", "s#1"]
    assert result.diagnostics["fallback"] is None


def test_fork_includes_parent_prefix_but_not_sibling_branch(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed_source(sessions)
    child = sessions.fork_session_before_user_index(
        source.key, "websocket:child", 1, include_user_message=True
    )
    child.add_message("user", "Consider approach B")
    sessions.save(child)

    result = GraphContextEngine(load_session=sessions.read_session_snapshot).build_context(
        sessions.read_session_snapshot(child.key)
    )

    assert texts(result) == [
        "Start project",
        "Use approach A",
        "A later question",
        "Consider approach B",
    ]
    assert "A later answer" not in texts(result)
    assert result.diagnostics["branch_count"] == 1


def test_walks_past_fork_into_grandparent_even_if_child_prefix_is_trimmed(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed_source(sessions)
    child = sessions.fork_session_before_user_index(
        source.key, "websocket:child", 1, include_user_message=True
    )
    child.add_message("user", "Consider approach B")
    sessions.save(child)
    grandchild = sessions.fork_session_before_user_index(
        child.key, "websocket:grandchild", 2, include_user_message=True
    )
    grandchild.add_message("user", "Deeper question")
    sessions.save(grandchild)

    snapshot = sessions.read_session_snapshot(grandchild.key)
    for message in snapshot.messages[:4]:
        message["content"] = "TRIMMED"

    result = GraphContextEngine(load_session=sessions.read_session_snapshot).build_context(
        snapshot
    )

    assert texts(result) == [
        "Start project",
        "Use approach A",
        "A later question",
        "Consider approach B",
        "Deeper question",
    ]
    assert result.diagnostics["branch_count"] == 2


def test_context_edge_pulls_in_another_sessions_history(tmp_path):
    sessions = make_manager(tmp_path)
    other = sessions.get_or_create("websocket:other")
    other.add_message("user", "Other question")
    other.add_message("assistant", "Other answer")
    sessions.save(other)
    main = Session(
        key="websocket:main",
        messages=[
            {"role": "user", "content": "Main question"},
            {"role": "assistant", "content": "Main answer"},
        ],
        metadata={
            "context_edges": [
                {"source": ["websocket:other", 1], "target": ["websocket:main", 0]}
            ]
        },
    )

    result = GraphContextEngine(load_session=sessions.read_session_snapshot).build_context(main)

    assert texts(result) == ["Other question", "Other answer", "Main question", "Main answer"]
    assert result.reasons["websocket:other#1"] == "context"


def test_token_budget_trims_oldest_and_reports_pruned():
    messages = []
    for i in range(6):
        messages.append({"role": "user", "content": f"question {i} " + "word " * 40})
        messages.append({"role": "assistant", "content": f"answer {i} " + "word " * 40})
    session = Session(key="s", messages=messages)

    result = GraphContextEngine().build_context(session, max_tokens=150)

    assert 0 < len(result.messages) < len(messages)
    assert result.messages[-1]["content"].startswith("answer 5")
    assert result.diagnostics["pruned"] == len(messages) - len(result.messages)


def test_missing_source_session_falls_back_to_linear(tmp_path):
    sessions = make_manager(tmp_path)
    source = seed_source(sessions)
    child = sessions.fork_session_before_user_index(
        source.key, "websocket:child", 1, include_user_message=True
    )
    child.add_message("user", "Consider approach B")
    sessions.save(child)

    result = GraphContextEngine(load_session=lambda key: None).build_context(
        sessions.read_session_snapshot(child.key)
    )

    assert texts(result)[-1] == "Consider approach B"
    assert result.diagnostics["fallback"]


def test_merged_forks_pass_through_context_builder_unchanged(tmp_path):
    from nanobot.agent.context import ContextBuilder, TranscriptInput

    sessions = make_manager(tmp_path)
    source = seed_source(sessions)
    fork_a = sessions.fork_session_before_user_index(
        source.key, "websocket:a", 1, include_user_message=True
    )
    fork_a.add_message("user", "Branch A work")
    sessions.save(fork_a)
    fork_b = sessions.fork_session_before_user_index(
        source.key, "websocket:b", 1, include_user_message=True
    )
    fork_b.add_message("user", "Branch B work")
    fork_b.metadata["context_edges"] = [
        {"source": ["websocket:a", 3], "target": ["websocket:b", 3]}
    ]
    sessions.save(fork_b)

    result = GraphContextEngine(load_session=sessions.read_session_snapshot).build_context(
        sessions.read_session_snapshot(fork_b.key)
    )
    transcript = ContextBuilder(tmp_path).build_transcript(
        TranscriptInput(history=result.messages, current_message="next")
    )

    assert texts(result)[-2:] == ["Branch A work", "Branch B work"]
    assert [m["content"] for m in transcript[1:-1]] == texts(result)
    assert transcript[-1]["role"] == "user"
