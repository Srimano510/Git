"""Context resolution for workflow node execution."""

from __future__ import annotations

from typing import Any

from nanobot.workflow.models import (
    EdgeType,
    ExecutionContext,
    WorkflowGraph,
)


class ContextResolver:
    """Resolve inputs for a node from the current execution context."""

    _CONTEXT_EDGE_TYPES = frozenset({
        EdgeType.CONTEXT,
        EdgeType.DEPENDENCY,
        EdgeType.CONDITION,
    })

    def __init__(self, graph: WorkflowGraph) -> None:
        self.graph = graph

    def resolve(
        self,
        node_id: str,
        execution_context: ExecutionContext,
    ) -> dict[str, Any]:
        """Build the input context available to one workflow node."""
        if node_id not in self.graph.nodes:
            raise ValueError(f"unknown workflow node: {node_id}")

        resolved: dict[str, Any] = {
            "user_input": execution_context.user_input,
            "variables": dict(execution_context.variables),
            "nodes": {},
        }

        for edge in self.graph.incoming(node_id):
            if edge.type not in self._CONTEXT_EDGE_TYPES:
                continue

            if edge.source not in execution_context.node_outputs:
                continue

            output = execution_context.node_outputs[edge.source]
            resolved["nodes"][edge.source] = self._select_fields(
                output,
                edge.provides,
            )

        return resolved

    @staticmethod
    def _select_fields(
        output: Any,
        fields: tuple[str, ...],
    ) -> Any:
        """Restrict a mapping output when an edge specifies ``provides``."""
        if not fields:
            return output

        if not isinstance(output, dict):
            raise ValueError(
                "edge provides fields, but the source output is not an object"
            )

        missing = [
            field
            for field in fields
            if field not in output
        ]
        if missing:
            raise ValueError(
                f"source output is missing provided fields: {', '.join(missing)}"
            )

        return {
            field: output[field]
            for field in fields
        }