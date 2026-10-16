from nanobot.context_graph.model import ConversationGraph, EdgeType
from nanobot.context_graph.resolver import get_ancestor_context


def n(i: int) -> tuple[str, int]:
    return ("s", i)


def test_diamond_merge_includes_all_parents_in_topological_order():
    graph = ConversationGraph()
    graph.add_edge(n(1), n(2), EdgeType.REPLY)
    graph.add_edge(n(1), n(3), EdgeType.REPLY)
    graph.add_edge(n(2), n(4), EdgeType.REPLY)
    graph.add_edge(n(3), n(4), EdgeType.REPLY)

    nodes, reasons = get_ancestor_context(graph, n(4))

    assert nodes == [n(1), n(2), n(3), n(4)]
    assert reasons[n(4)] == "current"


def test_root_returns_only_itself():
    nodes, _ = get_ancestor_context(ConversationGraph(), n(7))

    assert nodes == [n(7)]


def test_unmerged_branches_are_isolated():
    graph = ConversationGraph()
    graph.add_edge(n(1), n(2), EdgeType.REPLY)
    graph.add_edge(n(2), n(3), EdgeType.REPLY)  # branch A
    graph.add_edge(n(2), n(4), EdgeType.BRANCH)  # branch B

    nodes, reasons = get_ancestor_context(graph, n(4))

    assert nodes == [n(1), n(2), n(4)]
    assert n(3) not in nodes
    assert reasons[n(2)] == "branch"
    assert reasons[n(1)] == "reply"


def test_context_edges_are_followed_but_summary_and_reference_are_not():
    graph = ConversationGraph()
    graph.add_edge(n(1), n(5), EdgeType.CONTEXT)
    graph.add_edge(n(2), n(5), EdgeType.SUMMARY)
    graph.add_edge(n(3), n(5), EdgeType.REFERENCE)

    nodes, reasons = get_ancestor_context(graph, n(5))

    assert nodes == [n(1), n(5)]
    assert reasons[n(1)] == "context"


def test_cycle_terminates_and_returns_each_node_once():
    graph = ConversationGraph()
    graph.add_edge(n(1), n(2), EdgeType.REPLY)
    graph.add_edge(n(2), n(1), EdgeType.REPLY)

    nodes, _ = get_ancestor_context(graph, n(2))

    assert sorted(nodes) == [n(1), n(2)]
