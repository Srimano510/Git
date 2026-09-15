"""Core data structures for context-aware workflow DAGs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class NodeType(StrEnum):
    INPUT = "INPUT"
    INTENT = "INTENT"
    CONTEXT = "CONTEXT"
    MEMORY = "MEMORY"
    WEB_SEARCH = "WEB_SEARCH"
    FILE_SEARCH = "FILE_SEARCH"
    PROMPT_TEMPLATE = "PROMPT_TEMPLATE"
    LLM_CALL = "LLM_CALL"
    TOOL = "TOOL"
    MERGE = "MERGE"
    VALIDATION = "VALIDATION"
    SUMMARIZATION = "SUMMARIZATION"
    OUTPUT = "OUTPUT"


class EdgeType(StrEnum):
    EXECUTION = "EXECUTION"
    DEPENDENCY = "DEPENDENCY"
    CONTEXT = "CONTEXT"
    CONDITION = "CONDITION"
    SUMMARY = "SUMMARY"
    REFERENCE = "REFERENCE"


SCHEDULING_EDGE_TYPES = frozenset({
    EdgeType.EXECUTION,
    EdgeType.DEPENDENCY,
    EdgeType.CONTEXT,
    EdgeType.CONDITION,
})


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    id: str
    name: str
    type: NodeType
    prompt: str | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    version: str = "v1"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "prompt": self.prompt,
            "config": dict(self.config),
            "version": self.version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowNode:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            type=NodeType(str(data["type"])),
            prompt=data.get("prompt"),
            config=dict(data.get("config") or {}),
            version=str(data.get("version", "v1")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    id: str
    source: str
    target: str
    type: EdgeType
    condition: str | None = None
    provides: tuple[str, ...] = ()
    priority: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "type": self.type.value,
            "condition": self.condition,
            "provides": list(self.provides),
            "priority": self.priority,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowEdge:
        return cls(
            id=str(data["id"]),
            source=str(data["source"]),
            target=str(data["target"]),
            type=EdgeType(str(data["type"])),
            condition=data.get("condition"),
            provides=tuple(str(item) for item in data.get("provides") or ()),
            priority=int(data.get("priority", 0)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(slots=True)
class WorkflowGraph:
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    edges: dict[str, WorkflowEdge] = field(default_factory=dict)

    def add_node(self, node: WorkflowNode) -> None:
        if node.id in self.nodes:
            raise ValueError(f"duplicate workflow node: {node.id}")
        self.nodes[node.id] = node

    def add_edge(self, edge: WorkflowEdge) -> None:
        if edge.id in self.edges:
            raise ValueError(f"duplicate workflow edge: {edge.id}")
        self.edges[edge.id] = edge

    def outgoing(self, node_id: str) -> list[WorkflowEdge]:
        return sorted(
            (edge for edge in self.edges.values() if edge.source == node_id),
            key=lambda edge: (edge.priority, edge.id),
        )

    def incoming(self, node_id: str) -> list[WorkflowEdge]:
        return sorted(
            (edge for edge in self.edges.values() if edge.target == node_id),
            key=lambda edge: (edge.priority, edge.id),
        )

    def validate(self) -> None:
        for edge in self.edges.values():
            if edge.source not in self.nodes:
                raise ValueError(
                    f"edge {edge.id} references missing source: {edge.source}"
                )
            if edge.target not in self.nodes:
                raise ValueError(
                    f"edge {edge.id} references missing target: {edge.target}"
                )

        indegree = {node_id: 0 for node_id in self.nodes}
        adjacency: dict[str, list[str]] = {
            node_id: [] for node_id in self.nodes
        }

        for edge in self.edges.values():
            if edge.type not in SCHEDULING_EDGE_TYPES:
                continue

            adjacency[edge.source].append(edge.target)
            indegree[edge.target] += 1

        ready = sorted(
            node_id
            for node_id, count in indegree.items()
            if count == 0
        )

        visited = 0

        while ready:
            node_id = ready.pop(0)
            visited += 1

            for child_id in sorted(adjacency[node_id]):
                indegree[child_id] -= 1

                if indegree[child_id] == 0:
                    ready.append(child_id)
                    ready.sort()

        if visited != len(self.nodes):
            raise ValueError(
                "workflow graph contains a cycle in scheduling edges"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                node.to_dict()
                for node in self.nodes.values()
            ],
            "edges": [
                edge.to_dict()
                for edge in self.edges.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowGraph:
        graph = cls()

        for raw_node in data.get("nodes", ()):
            graph.add_node(WorkflowNode.from_dict(raw_node))

        for raw_edge in data.get("edges", ()):
            graph.add_edge(WorkflowEdge.from_dict(raw_edge))

        graph.validate()
        return graph


@dataclass(slots=True)
class ExecutionContext:
    user_input: str
    variables: dict[str, Any] = field(default_factory=dict)
    node_outputs: dict[str, Any] = field(default_factory=dict)
    session_key: str | None = None


@dataclass(frozen=True, slots=True)
class NodeResult:
    output: Any
    status: str = "succeeded"
    error: str | None = None