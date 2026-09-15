"""Service boundary for executing workflow graphs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from nanobot.workflow.executor import (
    NodeHandler,
    WorkflowExecutor,
    WorkflowRunResult,
)
from nanobot.workflow.models import (
    ExecutionContext,
    NodeType,
    WorkflowGraph,
)


@dataclass(frozen=True, slots=True)
class WorkflowRequest:
    """Inputs for one isolated workflow execution."""

    user_input: str
    variables: Mapping[str, Any] = field(default_factory=dict)
    session_key: str | None = None


class WorkflowService:
    """Create isolated execution contexts and run workflow graphs."""

    def __init__(
        self,
        graph: WorkflowGraph,
        handlers: Mapping[NodeType, NodeHandler] | None = None,
        graph_version: str = "v1",
    ) -> None:
        self.graph = graph
        self.handlers = dict(handlers or {})
        self.graph_version = graph_version

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        handlers: Mapping[NodeType, NodeHandler] | None = None,
        graph_version: str = "v1",
    ) -> WorkflowService:
        return cls(
            graph=WorkflowGraph.from_dict(data),
            handlers=handlers,
            graph_version=graph_version,
        )

    async def run(
        self,
        request: WorkflowRequest,
    ) -> WorkflowRunResult:
        """Execute one graph run with an isolated context."""
        context = ExecutionContext(
            user_input=request.user_input,
            variables=dict(request.variables),
            session_key=request.session_key,
        )

        result = await WorkflowExecutor(
            graph=self.graph,
            handlers=self.handlers,
        ).run(context)

        if result.transcript is not None:
            result.transcript.graph_version = self.graph_version

        return result