import asyncio

import pytest

from nanobot.workflow.executor import WorkflowExecutor
from nanobot.workflow.models import (
    EdgeType,
    ExecutionContext,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)


def test_executor_follows_matching_conditional_edge() -> None:
    graph = WorkflowGraph()

    graph.add_node(
        WorkflowNode(
            id="intent",
            name="Intent",
            type=NodeType.INTENT,
        )
    )
    graph.add_node(
        WorkflowNode(
            id="research",
            name="Research",
            type=NodeType.WEB_SEARCH,
        )
    )
    graph.add_node(
        WorkflowNode(
            id="writing",
            name="Writing",
            type=NodeType.PROMPT_TEMPLATE,
        )
    )

    graph.add_edge(
        WorkflowEdge(
            id="intent-research",
            source="intent",
            target="research",
            type=EdgeType.CONDITION,
            condition="intent == 'research'",
        )
    )
    graph.add_edge(
        WorkflowEdge(
            id="intent-writing",
            source="intent",
            target="writing",
            type=EdgeType.CONDITION,
            condition="intent == 'writing'",
        )
    )

    async def intent_handler(
        node: WorkflowNode,
        inputs: dict,
    ) -> dict:
        return {"intent": "research"}

    async def research_handler(
        node: WorkflowNode,
        inputs: dict,
    ) -> str:
        return "research completed"

    async def writing_handler(
        node: WorkflowNode,
        inputs: dict,
    ) -> str:
        return "writing completed"

    executor = WorkflowExecutor(
        graph,
        handlers={
            NodeType.INTENT: intent_handler,
            NodeType.WEB_SEARCH: research_handler,
            NodeType.PROMPT_TEMPLATE: writing_handler,
        },
    )

    result = asyncio.run(
        executor.run(
            ExecutionContext(user_input="Find recent research")
        )
    )

    assert result.context.node_outputs["intent"] == {
        "intent": "research",
    }
    assert result.context.node_outputs["research"] == "research completed"
    assert "writing" not in result.context.node_outputs

    statuses = {
        execution.node_id: execution.status
        for execution in result.executions
    }

    assert statuses == {
        "intent": "succeeded",
        "research": "succeeded",
        "writing": "skipped",
    }


def test_executor_records_failed_node() -> None:
    graph = WorkflowGraph()
    graph.add_node(
        WorkflowNode(
            id="broken",
            name="Broken Node",
            type=NodeType.TOOL,
        )
    )

    async def broken_handler(
        node: WorkflowNode,
        inputs: dict,
    ) -> None:
        raise RuntimeError("tool failed")

    executor = WorkflowExecutor(
        graph,
        handlers={
            NodeType.TOOL: broken_handler,
        },
    )

    result = asyncio.run(
        executor.run(
            ExecutionContext(user_input="Run tool")
        )
    )

    assert len(result.executions) == 1
    assert result.executions[0].node_id == "broken"
    assert result.executions[0].status == "failed"
    assert result.executions[0].error == "tool failed"


def test_invalid_condition_is_rejected() -> None:
    graph = WorkflowGraph()
    graph.add_node(
        WorkflowNode(
            id="intent",
            name="Intent",
            type=NodeType.INTENT,
        )
    )
    graph.add_node(
        WorkflowNode(
            id="next",
            name="Next",
            type=NodeType.OUTPUT,
        )
    )
    graph.add_edge(
        WorkflowEdge(
            id="invalid-condition",
            source="intent",
            target="next",
            type=EdgeType.CONDITION,
            condition="unsupported expression",
        )
    )

    async def intent_handler(
        node: WorkflowNode,
        inputs: dict,
    ) -> dict:
        return {"intent": "research"}

    executor = WorkflowExecutor(
        graph,
        handlers={
            NodeType.INTENT: intent_handler,
        },
    )

    with pytest.raises(ValueError, match="unsupported workflow condition"):
        asyncio.run(
            executor.run(
                ExecutionContext(user_input="Test")
            )
        )