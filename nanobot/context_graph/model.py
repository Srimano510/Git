from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4
import time


class EdgeType(str, Enum):
    REPLY = "REPLY"
    BRANCH = "BRANCH"
    CONTEXT = "CONTEXT"
    REFERENCE = "REFERENCE"
    SUMMARY = "SUMMARY"


@dataclass
class ChatNode:
    id: str
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)

    # Repository provenance
    session_key: str | None = None
    session_message_index: int | None = None
    turn_id: str | None = None
    message_id: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        role: str,
        content: str,
        session_key: str | None = None,
        session_message_index: int | None = None,
        turn_id: str | None = None,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ChatNode":
        return cls(
            id=f"node_{uuid4().hex}",
            role=role,
            content=content,
            session_key=session_key,
            session_message_index=session_message_index,
            turn_id=turn_id,
            message_id=message_id,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "session_key": self.session_key,
            "session_message_index": self.session_message_index,
            "turn_id": self.turn_id,
            "message_id": self.message_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatNode":
        return cls(
            id=data["id"],
            role=data["role"],
            content=data.get("content", ""),
            timestamp=float(data.get("timestamp", time.time())),
            session_key=data.get("session_key"),
            session_message_index=data.get("session_message_index"),
            turn_id=data.get("turn_id"),
            message_id=data.get("message_id"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ChatEdge:
    source: str
    target: str
    type: EdgeType

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.type, EdgeType):
            object.__setattr__(self, "type", EdgeType(self.type))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatEdge":
        return cls(
            source=data["source"],
            target=data["target"],
            type=EdgeType(data["type"]),
            metadata=dict(data.get("metadata") or {}),
        )


class ConversationGraph:
    """
    In-memory conversation graph.

    A node may have multiple children.
    This is what allows conversation branching.

    The graph itself does not create or fork nanobot sessions.
    Nanobot remains responsible for actual session creation.
    """

    def __init__(
        self,
        graph_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.graph_id = graph_id or f"graph_{uuid4().hex}"
        self.metadata = metadata or {}

        self.nodes: dict[str, ChatNode] = {}
        self.edges: list[ChatEdge] = []

        # Session -> graph-node mapping.
        self.session_nodes: dict[str, list[str]] = {}

        # (session_key, message_index) -> node_id
        self.provenance_index: dict[tuple[str, int], str] = {}

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    def add_node(self, node: ChatNode) -> ChatNode:
        existing = self.nodes.get(node.id)

        if existing is not None:
            return existing

        # Idempotency based on session provenance.
        if (
            node.session_key is not None
            and node.session_message_index is not None
        ):
            key = (
                node.session_key,
                node.session_message_index,
            )

            existing_id = self.provenance_index.get(key)

            if existing_id is not None:
                return self.nodes[existing_id]

            self.provenance_index[key] = node.id

        self.nodes[node.id] = node

        if node.session_key is not None:
            self.session_nodes.setdefault(node.session_key, [])

            if node.id not in self.session_nodes[node.session_key]:
                self.session_nodes[node.session_key].append(node.id)

        return node

    def get_node(self, node_id: str) -> ChatNode | None:
        return self.nodes.get(node_id)

    def add_provenance(self, session_key: str, message_index: int, node_id: str) -> None:
        if node_id not in self.nodes:
            raise ValueError(f"Unknown node for provenance: {node_id}")

        key = (session_key, message_index)
        existing_id = self.provenance_index.get(key)
        if existing_id is not None and existing_id != node_id:
            raise ValueError(f"Conflicting provenance for {session_key} message {message_index}")

        self.provenance_index[key] = node_id
        nodes = self.session_nodes.setdefault(session_key, [])
        if node_id not in nodes:
            nodes.append(node_id)

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source: str | ChatEdge,
        target: str | None = None,
        edge_type: EdgeType | str = EdgeType.REPLY,
        metadata: dict[str, Any] | None = None,
    ) -> ChatEdge:
        if isinstance(source, ChatEdge):
            edge = source
            source = edge.source
            target = edge.target
            edge_type = edge.type
            metadata = edge.metadata
        if target is None:
            raise TypeError("target is required when source is a node ID")
        if source not in self.nodes:
            raise ValueError(f"Unknown source node: {source}")

        if target not in self.nodes:
            raise ValueError(f"Unknown target node: {target}")

        edge_type = EdgeType(edge_type)

        # Idempotency.
        for edge in self.edges:
            if (
                edge.source == source
                and edge.target == target
                and edge.type == edge_type
            ):
                return edge

        edge = ChatEdge(
            source=source,
            target=target,
            type=edge_type,
            metadata=metadata or {},
        )

        self.edges.append(edge)

        return edge

    def has_edge(
        self,
        source: str,
        target: str,
        edge_type: EdgeType | str,
    ) -> bool:
        edge_type = EdgeType(edge_type)

        return any(
            edge.source == source
            and edge.target == target
            and edge.type == edge_type
            for edge in self.edges
        )

    def incoming_edges(self, node_id: str) -> list[ChatEdge]:
        return [edge for edge in self.edges if edge.target == node_id]

    def outgoing_edges(self, node_id: str) -> list[ChatEdge]:
        return [edge for edge in self.edges if edge.source == node_id]

    # ------------------------------------------------------------------
    # Branching
    # ------------------------------------------------------------------

    def add_branch(
        self,
        source_node_id: str,
        target_node_id: str,
        *,
        source_session: str | None = None,
        child_session: str | None = None,
        fork_boundary: int | None = None,
    ) -> ChatEdge:
        """
        Connect a child-session message to the source-session
        boundary using a BRANCH edge.
        """

        metadata: dict[str, Any] = {}

        if source_session is not None:
            metadata["source_session"] = source_session

        if child_session is not None:
            metadata["child_session"] = child_session

        if fork_boundary is not None:
            metadata["fork_boundary"] = fork_boundary

        return self.add_edge(
            source_node_id,
            target_node_id,
            EdgeType.BRANCH,
            metadata,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def children(
        self,
        node_id: str,
        edge_type: EdgeType | str | None = None,
    ) -> list[ChatNode]:
        if edge_type is not None:
            edge_type = EdgeType(edge_type)

        result = []

        for edge in self.edges:
            if edge.source != node_id:
                continue

            if edge_type is not None and edge.type != edge_type:
                continue

            node = self.nodes.get(edge.target)

            if node is not None:
                result.append(node)

        return result

    def parents(
        self,
        node_id: str,
        edge_type: EdgeType | str | None = None,
    ) -> list[ChatNode]:
        if edge_type is not None:
            edge_type = EdgeType(edge_type)

        result = []

        for edge in self.edges:
            if edge.target != node_id:
                continue

            if edge_type is not None and edge.type != edge_type:
                continue

            node = self.nodes.get(edge.source)

            if node is not None:
                result.append(node)

        return result

    def branch_edges(self) -> list[ChatEdge]:
        return [
            edge
            for edge in self.edges
            if edge.type == EdgeType.BRANCH
        ]

    def branch_count(self) -> int:
        return len(self.branch_edges())

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "metadata": self.metadata,
            "nodes": [
                node.to_dict()
                for node in self.nodes.values()
            ],
            "edges": [
                edge.to_dict()
                for edge in self.edges
            ],
            "session_nodes": self.session_nodes,
            "provenance_index": [
                {
                    "session_key": session_key,
                    "message_index": message_index,
                    "node_id": node_id,
                }
                for (session_key, message_index), node_id in self.provenance_index.items()
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationGraph":
        graph = cls(
            graph_id=data.get("graph_id"),
            metadata=dict(data.get("metadata") or {}),
        )

        for node_data in data.get("nodes", []):
            graph.add_node(
                ChatNode.from_dict(node_data)
            )

        for edge_data in data.get("edges", []):
            edge = ChatEdge.from_dict(edge_data)

            if (
                edge.source in graph.nodes
                and edge.target in graph.nodes
            ):
                graph.edges.append(edge)

        provenance = data.get("provenance_index", [])
        if isinstance(provenance, list):
            for entry in provenance:
                if not isinstance(entry, dict):
                    continue
                session_key = entry.get("session_key")
                message_index = entry.get("message_index")
                node_id = entry.get("node_id")
                if (
                    isinstance(session_key, str)
                    and isinstance(message_index, int)
                    and not isinstance(message_index, bool)
                    and isinstance(node_id, str)
                    and node_id in graph.nodes
                ):
                    graph.add_provenance(session_key, message_index, node_id)

        return graph

    @classmethod
    def from_json(cls, data: str) -> "ConversationGraph":
        return cls.from_dict(json.loads(data))