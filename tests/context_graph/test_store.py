"""Unit tests for Context Graph storage and synchronization."""

from pathlib import Path

from nanobot.context_graph.model import ChatNode, ConversationGraph
from nanobot.context_graph.store import ContextGraphStore


def test_context_graph_store_save_and_load(tmp_path: Path):
    store = ContextGraphStore(root_dir=tmp_path)
    session_key = "websocket:test-store-chat"

    graph = ConversationGraph(metadata={"session_key": session_key})
    n1 = ChatNode(id="n1", role="user", content="Hello store")
    graph.add_node(n1)

    assert store.save_graph(session_key, graph) is True

    loaded = store.load_graph(session_key)
    assert len(loaded.nodes) == 1
    assert loaded.get_node("n1") is not None
    assert loaded.get_node("n1").content == "Hello store"


def test_context_graph_store_sync_messages(tmp_path: Path):
    store = ContextGraphStore(root_dir=tmp_path)
    session_key = "websocket:test-sync-chat"

    messages = [
        {"role": "user", "content": "What is Python?", "turn_id": "t1"},
        {"role": "assistant", "content": "Python is a language.", "turn_id": "t1"},
        {"role": "user", "content": "Tell me more.", "turn_id": "t2"},
    ]

    graph = store.sync_session_messages(session_key, messages)
    assert len(graph.nodes) == 3
    assert len(graph.edges) == 2

    # Verify idempotence: syncing the same messages should not duplicate nodes or edges
    graph_resynced = store.sync_session_messages(session_key, messages, graph=graph)
    assert len(graph_resynced.nodes) == 3
    assert len(graph_resynced.edges) == 2
