"""Unit tests for Context Graph data model."""

from nanobot.context_graph.model import (
    ChatEdge,
    ChatNode,
    ConversationGraph,
    EdgeType,
)


def test_chat_node_serialization():
    node = ChatNode(
        id="node_1",
        role="user",
        content="Hello world",
        timestamp=1000.0,
        session_key="websocket:test-chat",
        session_message_index=0,
        turn_id="turn_abc",
        metadata={"custom": "field"},
    )
    data = node.to_dict()
    assert data["id"] == "node_1"
    assert data["role"] == "user"
    assert data["content"] == "Hello world"
    assert data["session_key"] == "websocket:test-chat"
    assert data["session_message_index"] == 0
    assert data["turn_id"] == "turn_abc"
    assert data["metadata"]["custom"] == "field"

    restored = ChatNode.from_dict(data)
    assert restored.id == node.id
    assert restored.role == node.role
    assert restored.content == node.content
    assert restored.session_key == node.session_key
    assert restored.session_message_index == node.session_message_index
    assert restored.turn_id == node.turn_id
    assert restored.metadata == node.metadata


def test_chat_edge_serialization():
    edge = ChatEdge(
        source="node_1",
        target="node_2",
        type=EdgeType.REPLY.value,
        metadata={"confidence": 0.95},
    )
    data = edge.to_dict()
    assert data["source"] == "node_1"
    assert data["target"] == "node_2"
    assert data["type"] == "REPLY"
    assert data["metadata"]["confidence"] == 0.95

    restored = ChatEdge.from_dict(data)
    assert restored.source == edge.source
    assert restored.target == edge.target
    assert restored.type == edge.type
    assert restored.metadata == edge.metadata


def test_conversation_graph_operations():
    graph = ConversationGraph()
    n1 = ChatNode(id="n1", role="user", content="Question 1")
    n2 = ChatNode(id="n2", role="assistant", content="Answer 1")
    n3 = ChatNode(id="n3", role="user", content="Question 2")

    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)

    e1 = ChatEdge(source="n1", target="n2", type=EdgeType.REPLY.value)
    e2 = ChatEdge(source="n2", target="n3", type=EdgeType.REPLY.value)
    graph.add_edge(e1)
    graph.add_edge(e2)

    assert graph.get_node("n1") == n1
    assert graph.get_node("n2") == n2
    assert graph.get_node("unknown") is None

    assert len(graph.incoming_edges("n2")) == 1
    assert graph.incoming_edges("n2")[0].source == "n1"
    assert len(graph.outgoing_edges("n2")) == 1
    assert graph.outgoing_edges("n2")[0].target == "n3"


def test_conversation_graph_json_roundtrip():
    graph = ConversationGraph(metadata={"session_id": "s123"})
    n1 = ChatNode(id="n1", role="user", content="Let's design an API.")
    n2 = ChatNode(id="n2", role="assistant", content="We can use REST.")
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_edge(ChatEdge(source="n1", target="n2", type=EdgeType.REPLY.value))

    json_str = graph.to_json()
    restored = ConversationGraph.from_json(json_str)

    assert len(restored.nodes) == 2
    assert len(restored.edges) == 1
    assert restored.metadata["session_id"] == "s123"
    assert restored.get_node("n1") is not None
    assert restored.get_node("n1").content == "Let's design an API."
    assert restored.edges[0].source == "n1"
    assert restored.edges[0].target == "n2"
