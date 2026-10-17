from unittest.mock import MagicMock

from nanobot.agent.context import ContextBuilder, TranscriptInput
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ContextGraphConfig
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


def archived_session(key="cli:c"):
    s = Session(key=key)
    s.add_message("user", "Which database should the orders service use?")
    s.add_message("assistant", "Use Postgres for the orders database.")
    for i in range(6):
        s.add_message("user", f"fun fact request {i}")
        s.add_message("assistant", f"bananas are berries {i}")
    s.last_archived = 4
    return s


def test_hybrid_turn_recalls_and_records_what_was_used(tmp_path):
    loop = make_loop(tmp_path)
    s = archived_session()
    result = loop._graph_context(s, "hybrid", QUERY, extend_to_user=False)

    assert "Postgres" in result.recalled
    assert result.strategy == "hybrid" and result.diagnostics["pool"] == "archived"
    last = s.metadata["_last_context"]
    assert last["strategy"] == "hybrid"
    assert last["nodes"]["cli:c#1"] == "vector"
    assert last["nodes"]["cli:c#11"] == "history"


def test_graph_turn_has_no_recall_and_still_records_history(tmp_path):
    loop = make_loop(tmp_path)
    s = archived_session()
    result = loop._graph_context(s, "graph", QUERY, extend_to_user=False)
    assert result.recalled == "" and result.strategy == "graph"
    assert set(s.metadata["_last_context"]["nodes"].values()) == {"history"}


def test_session_pool_override_beats_the_config_default(tmp_path):
    loop = make_loop(tmp_path, context_graph_config=ContextGraphConfig(semantic_pool="archived"))
    s = archived_session()
    assert loop._graph_context(s, "hybrid", QUERY, False).diagnostics["pool"] == "archived"
    s.metadata["context_pool"] = "family"
    assert loop._graph_context(s, "hybrid", QUERY, False).diagnostics["pool"] == "family"


def test_config_default_pool_is_used_when_there_is_no_override(tmp_path):
    loop = make_loop(tmp_path, context_graph_config=ContextGraphConfig(semantic_pool="family"))
    assert loop._graph_context(archived_session(), "hybrid", QUERY, False).diagnostics["pool"] == "family"


def test_forks_do_not_inherit_the_parents_last_context(tmp_path):
    m = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    src = m.get_or_create("websocket:src")
    src.add_message("user", "q")
    src.add_message("assistant", "a")
    src.metadata["_last_context"] = {"strategy": "hybrid", "nodes": {"websocket:src#0": "vector"}}
    m.save(src)
    kid = m.fork_session_before_user_index(src.key, "websocket:kid", 1)
    assert "_last_context" not in kid.metadata


def test_recalled_context_reaches_the_system_prompt_only_when_present(tmp_path):
    builder = ContextBuilder(tmp_path)
    hist = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]
    with_recall = builder.build_transcript(
        TranscriptInput(history=hist, current_message="now", recalled_context="[user, similarity 0.5] Postgres")
    )
    plain = builder.build_transcript(TranscriptInput(history=hist, current_message="now"))

    assert "[Recalled Context]" in with_recall[0]["content"]
    assert "Postgres" in with_recall[0]["content"]
    assert "[Recalled Context]" not in plain[0]["content"]
    assert with_recall[1:] == plain[1:]  # history and current message untouched
