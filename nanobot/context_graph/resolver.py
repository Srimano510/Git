"""Pure DAG traversal: collect every ancestor reachable through typed edges."""

from __future__ import annotations

import heapq
from collections import defaultdict

from .model import ConversationGraph, EdgeType, NodeId

TRAVERSE_EDGE_TYPES = frozenset({EdgeType.REPLY, EdgeType.BRANCH, EdgeType.CONTEXT})


def get_ancestor_context(
    graph: ConversationGraph,
    current: NodeId,
    edge_types: frozenset[EdgeType] = TRAVERSE_EDGE_TYPES,
) -> tuple[list[NodeId], dict[NodeId, str]]:
    """Return ``current`` and all its ancestors, parents first, plus why each was kept.

    Order is topological with ties broken by ``(session_key, index)``; timestamps are not
    used because synced messages carry no reliable ordering time. Cycles are tolerated.
    """
    reasons: dict[NodeId, str] = {current: "current"}
    parents: dict[NodeId, set[NodeId]] = {}
    stack = [current]
    while stack:
        node = stack.pop()
        parents[node] = set()
        for edge in graph.incoming(node):
            if edge.type not in edge_types:
                continue
            parents[node].add(edge.source)
            if edge.source not in reasons:
                reasons[edge.source] = edge.type.value.lower()
                stack.append(edge.source)

    children: dict[NodeId, list[NodeId]] = defaultdict(list)
    waiting = {node: len(ps) for node, ps in parents.items()}
    for node, ps in parents.items():
        for parent in ps:
            children[parent].append(node)
    ready = [node for node, count in waiting.items() if count == 0]
    heapq.heapify(ready)
    order: list[NodeId] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for child in children[node]:
            waiting[child] -= 1
            if waiting[child] == 0:
                heapq.heappush(ready, child)
    order.extend(sorted(set(parents) - set(order)))
    return order, reasons
