"""Async execution engine for workflow DAGs."""

from __future__ import annotations

import ast
import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from time import monotonic
from typing import Any
from uuid import uuid4

from nanobot.workflow.transcript import (
    TranscriptEntry,
    WorkflowTranscript,
)
from nanobot.workflow.context import ContextResolver
from nanobot.workflow.models import (
    EdgeType,
    ExecutionContext,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)


NodeHandler = Callable[
    [WorkflowNode, Mapping[str, Any]],
    Awaitable[Any] | Any,
]


@dataclass(frozen=True, slots=True)
class NodeExecution:
    node_id: str
    status: str
    duration_ms: int
    input: Any = None
    output: Any = None
    error: str | None = None


@dataclass(slots=True)
class WorkflowRunResult:
    context: ExecutionContext
    executions: list[NodeExecution] = field(default_factory=list)
    transcript: WorkflowTranscript | None = None

    @property
    def output(self) -> Any:
        for execution in reversed(self.executions):
            if execution.status == "succeeded" and execution.output is not None:
                return execution.output
        return None


class WorkflowExecutor:
    """Execute ready DAG nodes concurrently in deterministic batches."""

    _SCHEDULING_EDGE_TYPES = frozenset({
        EdgeType.EXECUTION,
        EdgeType.DEPENDENCY,
        EdgeType.CONTEXT,
        EdgeType.CONDITION,
    })

    _CONDITION_RE = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(==|!=)\s*(.+?)\s*$"
    )

    def __init__(
        self,
        graph: WorkflowGraph,
        handlers: Mapping[NodeType, NodeHandler] | None = None,
    ) -> None:
        graph.validate()
        self.graph = graph
        self.handlers = dict(handlers or {})
        self.context_resolver = ContextResolver(graph)

    async def run(
        self,
        execution_context: ExecutionContext,
    ) -> WorkflowRunResult:
        """Execute the graph and return its outputs and execution trace."""
        pending = set(self.graph.nodes)
        completed: set[str] = set()
        skipped: set[str] = set()
        executions: list[NodeExecution] = []
        transcript = WorkflowTranscript(
            run_id=uuid4().hex,
        )

        while pending:
            ready: list[WorkflowNode] = []
            newly_skipped: list[WorkflowNode] = []

            for node_id in sorted(pending):
                node = self.graph.nodes[node_id]
                incoming = self._scheduling_incoming(node_id)

                if not self._sources_resolved(incoming, completed, skipped):
                    continue

                if self._must_skip(incoming, completed, skipped, execution_context):
                    newly_skipped.append(node)
                elif self._has_active_incoming(incoming, completed, execution_context):
                    ready.append(node)
                elif not incoming:
                    ready.append(node)
                else:
                    newly_skipped.append(node)

            for node in newly_skipped:
                pending.remove(node.id)
                skipped.add(node.id)
                executions.append(
                    NodeExecution(
                        node_id=node.id,
                        status="skipped",
                        duration_ms=0,
                    )
                )
                transcript.add(
                    TranscriptEntry(
                        node_id=node.id,
                        node_name=node.name,
                        status="skipped",
                    )
                )

            if ready:
                results = await asyncio.gather(*(
                    self._execute_node(node, execution_context)
                    for node in ready
                ))

                for node, result in zip(ready, results, strict=True):
                    pending.remove(node.id)

                    if result.status == "succeeded":
                        execution_context.node_outputs[node.id] = result.output
                        completed.add(node.id)

                    executions.append(result)
                    transcript.add(
                        TranscriptEntry(
                            node_id=node.id,
                            node_name=node.name,
                            status=result.status,
                            input=result.input,
                            output=result.output,
                            error=result.error,
                            duration_ms=result.duration_ms,
                        )
                    )

                continue

            if pending:
                unresolved = ", ".join(sorted(pending))
                raise RuntimeError(
                    f"workflow cannot make progress; unresolved nodes: {unresolved}"
                )

        return WorkflowRunResult(
            context=execution_context,
            executions=executions,
            transcript=transcript,
        )

    async def _execute_node(
        self,
        node: WorkflowNode,
        execution_context: ExecutionContext,
    ) -> NodeExecution:
        started = monotonic()
        inputs: Mapping[str, Any] | None = None

        try:
            inputs = self.context_resolver.resolve(
                node.id,
                execution_context,
            )
            output = await self._call_handler(node, inputs)
        except Exception as error:
            return NodeExecution(
                node_id=node.id,
                status="failed",
                duration_ms=self._duration_ms(started),
                input=inputs,
                error=str(error),
            )

        return NodeExecution(
            node_id=node.id,
            status="succeeded",
            duration_ms=self._duration_ms(started),
            input=inputs,
            output=output,
        )

    async def _call_handler(
        self,
        node: WorkflowNode,
        inputs: Mapping[str, Any],
    ) -> Any:
        handler = self.handlers.get(node.type)

        if handler is not None:
            result = handler(node, inputs)
            if asyncio.iscoroutine(result):
                return await result
            return result

        if node.type is NodeType.INPUT:
            return inputs["user_input"]

        if node.type is NodeType.MERGE:
            return dict(inputs["nodes"])

        if node.type is NodeType.OUTPUT:
            return dict(inputs)

        raise ValueError(
            f"no handler registered for workflow node type: {node.type.value}"
        )

    def _scheduling_incoming(
        self,
        node_id: str,
    ) -> list[WorkflowEdge]:
        return [
            edge
            for edge in self.graph.incoming(node_id)
            if edge.type in self._SCHEDULING_EDGE_TYPES
        ]

    @staticmethod
    def _sources_resolved(
        incoming: list[WorkflowEdge],
        completed: set[str],
        skipped: set[str],
    ) -> bool:
        resolved = completed | skipped
        return all(edge.source in resolved for edge in incoming)

    def _must_skip(
        self,
        incoming: list[WorkflowEdge],
        completed: set[str],
        skipped: set[str],
        execution_context: ExecutionContext,
    ) -> bool:
        for edge in incoming:
            if edge.source in skipped and edge.condition is None:
                return True

        active_edges = [
            edge
            for edge in incoming
            if edge.source in completed
            and self._condition_matches(edge, execution_context)
        ]

        has_conditional_edge = any(
            edge.condition is not None
            for edge in incoming
        )

        return has_conditional_edge and not active_edges

    def _has_active_incoming(
        self,
        incoming: list[WorkflowEdge],
        completed: set[str],
        execution_context: ExecutionContext,
    ) -> bool:
        return any(
            edge.source in completed
            and self._condition_matches(edge, execution_context)
            for edge in incoming
        )

    def _condition_matches(
        self,
        edge: WorkflowEdge,
        execution_context: ExecutionContext,
    ) -> bool:
        if edge.condition is None:
            return True

        match = self._CONDITION_RE.match(edge.condition)
        if match is None:
            raise ValueError(
                f"unsupported workflow condition: {edge.condition}"
            )

        path, operator, raw_expected = match.groups()

        try:
            expected = ast.literal_eval(raw_expected)
        except (SyntaxError, ValueError) as error:
            raise ValueError(
                f"invalid workflow condition value: {raw_expected}"
            ) from error

        actual = self._resolve_value(
            path,
            execution_context,
        )

        if operator == "==":
            return actual == expected

        return actual != expected

    @staticmethod
    def _resolve_value(
        path: str,
        execution_context: ExecutionContext,
    ) -> Any:
        parts = path.split(".")

        if parts[0] in execution_context.variables:
            value: Any = execution_context.variables[parts[0]]
            parts = parts[1:]
        else:
            value = None
            for output in execution_context.node_outputs.values():
                if isinstance(output, dict) and parts[0] in output:
                    value = output[parts[0]]
                    parts = parts[1:]
                    break

            if value is None:
                raise ValueError(
                    f"workflow condition references unknown value: {path}"
                )

        for part in parts:
            if not isinstance(value, dict) or part not in value:
                raise ValueError(
                    f"workflow condition references unknown value: {path}"
                )
            value = value[part]

        return value

    @staticmethod
    def _duration_ms(started: float) -> int:
        return round((monotonic() - started) * 1000)