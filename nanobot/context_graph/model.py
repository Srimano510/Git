"""Typed-edge DAG over session messages.

A node is an address ``(session_key, message_index)`` into the session store, so no
message content is duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

NodeId = tuple[str, int]


class EdgeType(str, Enum):
    REPLY = "REPLY"
    BRANCH = "BRANCH"
    CONTEXT = "CONTEXT"
    REFERENCE = "REFERENCE"
    SUMMARY = "SUMMARY"


@dataclass(frozen=True)
class ChatEdge:
    source: NodeId
    target: NodeId
    type: EdgeType


class ConversationGraph:
    """Directed edges from parent (source) to child (target)."""

    def __init__(self) -> None:
        self.edges: list[ChatEdge] = []
        self._incoming: dict[NodeId, list[ChatEdge]] = {}

    def add_edge(self, source: NodeId, target: NodeId, type: EdgeType) -> None:
        edge = ChatEdge(source, target, type)
        if edge not in self._incoming.setdefault(target, []):
            self._incoming[target].append(edge)
            self.edges.append(edge)

    def incoming(self, node: NodeId) -> list[ChatEdge]:
        return self._incoming.get(node, [])
