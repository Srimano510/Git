import pytest

from nanobot.workflow.models import (
    EdgeType,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)


def make_node(node_id: str) -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        name=node_id.upper(),
        type=NodeType.CONTEXT,
    )


def test_graph_round_trip() -> None:
    graph = WorkflowGraph()
    graph.add_node(make_node("input"))
    graph.add_node(make_node("output"))
    graph.add_edge(
        WorkflowEdge(
            id="input-output",
            source="input",
            target="output",
            type=EdgeType.CONTEXT,
            provides=("query",),
        )
    )

    restored = WorkflowGraph.from_dict(graph.to_dict())

    assert restored.to_dict() == graph.to_dict()


def test_reference_edges_do_not_create_cycles() -> None:
    graph = WorkflowGraph()
    graph.add_node(make_node("a"))
    graph.add_node(make_node("b"))
    graph.add_edge(
        WorkflowEdge("a-b", "a", "b", EdgeType.EXECUTION)
    )
    graph.add_edge(
        WorkflowEdge("b-a", "b", "a", EdgeType.REFERENCE)
    )

    graph.validate()


def test_missing_target_is_rejected() -> None:
    graph = WorkflowGraph()
    graph.add_node(make_node("a"))
    graph.add_edge(
        WorkflowEdge(
            "a-missing",
            "a",
            "missing",
            EdgeType.EXECUTION,
        )
    )

    with pytest.raises(ValueError, match="missing target"):
        graph.validate()


def test_scheduling_cycle_is_rejected() -> None:
    graph = WorkflowGraph()
    graph.add_node(make_node("a"))
    graph.add_node(make_node("b"))
    graph.add_edge(
        WorkflowEdge("a-b", "a", "b", EdgeType.DEPENDENCY)
    )
    graph.add_edge(
        WorkflowEdge("b-a", "b", "a", EdgeType.DEPENDENCY)
    )

    with pytest.raises(ValueError, match="cycle"):
        graph.validate()