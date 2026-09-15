import asyncio

from nanobot.workflow.executor import WorkflowExecutor
from nanobot.workflow.models import (
    EdgeType,
    ExecutionContext,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)


def test_executor_runs_independent_nodes_before_merge() -> None:
    graph = WorkflowGraph()

    for node_id, node_type in (
        ("memory", NodeType.MEMORY),
        ("web", NodeType.WEB_SEARCH),
        ("merge", NodeType.MERGE),
    ):
        graph.add_node(
            WorkflowNode(
                id=node_id,
                name=node_id,
                type=node_type,
            )
        )

    graph.add_edge(
        WorkflowEdge(
            "memory-merge",
            "memory",
            "merge",
            EdgeType.CONTEXT,
        )
    )
    graph.add_edge(
        WorkflowEdge(
            "web-merge",
            "web",
            "merge",
            EdgeType.CONTEXT,
        )
    )

    async def handler(node: WorkflowNode, inputs: dict) -> dict:
        await asyncio.sleep(0)
        return {node.id: "complete"}

    executor = WorkflowExecutor(
        graph,
        handlers={
            NodeType.MEMORY: handler,
            NodeType.WEB_SEARCH: handler,
        },
    )

    result = asyncio.run(
        executor.run(
            ExecutionContext(user_input="hello")
        )
    )

    assert result.context.node_outputs == {
        "memory": {"memory": "complete"},
        "web": {"web": "complete"},
        "merge": {
            "memory": {"memory": "complete"},
            "web": {"web": "complete"},
        },
    }