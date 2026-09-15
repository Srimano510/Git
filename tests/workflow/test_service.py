import asyncio

from nanobot.workflow.models import (
    ExecutionContext,
    NodeType,
    WorkflowGraph,
    WorkflowNode,
)
from nanobot.workflow.service import (
    WorkflowRequest,
    WorkflowService,
)


def test_service_creates_isolated_execution_context() -> None:
    graph = WorkflowGraph()
    graph.add_node(
        WorkflowNode(
            id="input",
            name="Input",
            type=NodeType.INPUT,
        )
    )

    service = WorkflowService(graph)

    first = asyncio.run(
        service.run(
            WorkflowRequest(
                user_input="first message",
                variables={"request_id": "one"},
                session_key="session-one",
            )
        )
    )

    second = asyncio.run(
        service.run(
            WorkflowRequest(
                user_input="second message",
                variables={"request_id": "two"},
                session_key="session-two",
            )
        )
    )

    assert first.context.user_input == "first message"
    assert first.context.variables == {"request_id": "one"}
    assert first.context.session_key == "session-one"

    assert second.context.user_input == "second message"
    assert second.context.variables == {"request_id": "two"}
    assert second.context.session_key == "session-two"

    assert first.context is not second.context


def test_service_preserves_graph_version_in_transcript() -> None:
    graph = WorkflowGraph()
    graph.add_node(
        WorkflowNode(
            id="input",
            name="Input",
            type=NodeType.INPUT,
        )
    )

    service = WorkflowService(
        graph,
        graph_version="workflow-v2",
    )

    result = asyncio.run(
        service.run(
            WorkflowRequest(user_input="hello")
        )
    )

    assert result.transcript is not None
    assert result.transcript.graph_version == "workflow-v2"