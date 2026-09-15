import pytest

from nanobot.workflow.context import ContextResolver
from nanobot.workflow.models import (
    EdgeType,
    ExecutionContext,
    NodeType,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)


def make_graph() -> WorkflowGraph:
    graph = WorkflowGraph()

    graph.add_node(
        WorkflowNode("memory", "Memory", NodeType.MEMORY)
    )
    graph.add_node(
        WorkflowNode("prompt", "Prompt", NodeType.PROMPT_TEMPLATE)
    )

    graph.add_edge(
        WorkflowEdge(
            id="memory-prompt",
            source="memory",
            target="prompt",
            type=EdgeType.CONTEXT,
            provides=("snippet",),
        )
    )

    return graph


def test_resolver_includes_user_input_and_selected_fields() -> None:
    graph = make_graph()
    context = ExecutionContext(
        user_input="Plan a trip",
        variables={"language": "English"},
        node_outputs={
            "memory": {
                "snippet": "The user likes hiking.",
                "private_field": "hidden",
            }
        },
    )

    resolved = ContextResolver(graph).resolve("prompt", context)

    assert resolved["user_input"] == "Plan a trip"
    assert resolved["variables"] == {"language": "English"}
    assert resolved["nodes"] == {
        "memory": {
            "snippet": "The user likes hiking.",
        }
    }


def test_resolver_skips_unavailable_parent_outputs() -> None:
    graph = make_graph()
    context = ExecutionContext(user_input="Hello")

    resolved = ContextResolver(graph).resolve("prompt", context)

    assert resolved["nodes"] == {}


def test_resolver_rejects_missing_provided_fields() -> None:
    graph = make_graph()
    context = ExecutionContext(
        user_input="Hello",
        node_outputs={"memory": {"other": "value"}},
    )

    with pytest.raises(ValueError, match="missing provided fields"):
        ContextResolver(graph).resolve("prompt", context)