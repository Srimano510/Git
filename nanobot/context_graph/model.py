"""Conversation Graph data model for structured chat history."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast


class EdgeType(str, Enum):
    """Supported edge relationship types in conversation graphs."""

    REPLY = "REPLY"
    BRANCH = "BRANCH"
    SUMMARY = "SUMMARY"
    CONTEXT = "CONTEXT"
    REFERENCE = "REFERENCE"


@dataclass
class ChatNode:
    """A single message or summary node in the conversation graph."""

    id: str
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)
    session_key: str | None = None
    session_message_index: int | None = None
    turn_id: str | None = None
    message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.session_key is not None:
            result["session_key"] = self.session_key
        if self.session_message_index is not None:
            result["session_message_index"] = self.session_message_index
        if self.turn_id is not None:
            result["turn_id"] = self.turn_id
        if self.message_id is not None:
            result["message_id"] = self.message_id
        if self.metadata:
            result["metadata"] = self.metadata
        if self.embedding is not None:
            result["embedding"] = self.embedding
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatNode:
        return cls(
            id=str(data["id"]),
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            timestamp=float(data.get("timestamp", time.time())),
            session_key=data.get("session_key"),
            session_message_index=data.get("session_message_index"),
            turn_id=data.get("turn_id"),
            message_id=data.get("message_id"),
            metadata=dict(data.get("metadata", {})),
            embedding=data.get("embedding"),
        )


@dataclass
class ChatEdge:
    """A directed edge representing a relationship between two conversation nodes."""

    source: str
    target: str
    type: str = EdgeType.REPLY.value
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "type": self.type if isinstance(self.type, str) else self.type.value,
        }
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatEdge:
        return cls(
            source=str(data["source"]),
            target=str(data["target"]),
            type=str(data.get("type", EdgeType.REPLY.value)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ConversationGraph:
    """In-memory conversation graph holding chat nodes and relational edges."""

    nodes: dict[str, ChatNode] = field(default_factory=dict)
    edges: list[ChatEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: ChatNode) -> None:
        """Add or update a node in the graph."""
        self.nodes[node.id] = node

    def add_edge(self, edge: ChatEdge) -> None:
        """Add an edge to the graph."""
        self.edges.append(edge)

    def get_node(self, node_id: str) -> ChatNode | None:
        """Retrieve a node by its ID."""
        return self.nodes.get(node_id)

    def incoming_edges(self, node_id: str) -> list[ChatEdge]:
        """Get all edges pointing to the specified node."""
        return [edge for edge in self.edges if edge.target == node_id]

    def outgoing_edges(self, node_id: str) -> list[ChatEdge]:
        """Get all edges originating from the specified node."""
        return [edge for edge in self.edges if edge.source == node_id]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the conversation graph to a dictionary."""
        return {
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationGraph:
        """Construct a conversation graph from serialized dictionary data."""
        nodes: dict[str, ChatNode] = {}
        for raw_node in cast(list[dict[str, Any]], data.get("nodes", [])):
            node = ChatNode.from_dict(raw_node)
            nodes[node.id] = node

        edges: list[ChatEdge] = [
            ChatEdge.from_dict(raw_edge)
            for raw_edge in cast(list[dict[str, Any]], data.get("edges", []))
        ]

        metadata = dict(data.get("metadata", {}))
        return cls(nodes=nodes, edges=edges, metadata=metadata)

    def to_json(self, indent: int | None = 2) -> str:
        """Serialize graph to a JSON formatted string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> ConversationGraph:
        """Deserialize graph from a JSON string."""
        data = json.loads(json_str)
        if not isinstance(data, dict):
            raise ValueError("ConversationGraph JSON must be an object")
        return cls.from_dict(data)
