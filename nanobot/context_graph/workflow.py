"""Workflow DAG: an after-the-fact record of the steps that built one turn's context.

Steps are nodes ``("workflow", i)`` joined by ``TRIGGERS``/``FEEDS`` edges. The record lives
in session metadata, never in ``Session.messages``, and ``TRAVERSE_EDGE_TYPES`` does not
follow these edge types, so it can never reach the prompt.
"""

from __future__ import annotations

from typing import Any

from .model import ConversationGraph, EdgeType
from .observability import ContextResult

WORKFLOW_EDGES = frozenset({EdgeType.TRIGGERS, EdgeType.FEEDS})
GROUP = "workflow"


def build_workflow(result: ContextResult, at: int) -> dict[str, Any]:
    """Trace of a graph/hybrid turn. ``at`` is the message count when the context was built."""
    d = result.diagnostics
    hybrid = result.strategy == "hybrid"
    embed_ms = float(d.get("embed_ms") or 0.0) if hybrid else 0.0

    traversal = f"visited {d.get('visited', 0)}, returned {d.get('returned', 0)}, " \
        f"pruned {d.get('pruned', 0)}, branches {d.get('branch_count', 0)}"
    if d.get("fallback"):
        traversal += f"; fell back to linear: {d['fallback']}"
    steps: dict[str, dict[str, Any]] = {
        "strategy": {
            "label": "ContextStrategySelection", "type": "intent",
            "detail": result.strategy + (f", pool={d.get('pool')}" if hybrid else ""),
        },
        "traversal": {
            "label": "GraphTraversal", "type": "tool", "detail": traversal,
            "ms": round(result.retrieval_ms - embed_ms, 1),
        },
    }
    if hybrid:
        steps["search"] = {
            "label": "SemanticSearch", "type": "tool",
            "detail": d["semantic_error"] if d.get("semantic_error") else
            f"candidates {d.get('semantic_candidates', 0)}, hits {d.get('semantic_hits', 0)}, "
            f"included {d.get('semantic_included', 0)}, summaries {d.get('summaries_used', 0)}",
            "ms": round(embed_ms, 1),
        }
    steps["merge"] = {
        "label": "ContextMerge", "type": "merge", "detail": f"{len(result.node_ids)} nodes in context",
    }
    steps["prompt"] = {
        "label": "PromptBuild", "type": "prompt", "detail": f"{result.token_count} tokens",
    }
    steps["llm"] = {"label": "LLMCall", "type": "execution", "detail": ""}

    index = {name: i for i, name in enumerate(steps)}
    graph = ConversationGraph()
    for name in ("traversal", "search"):
        if name in steps:
            graph.add_edge((GROUP, 0), (GROUP, index[name]), EdgeType.TRIGGERS)
            graph.add_edge((GROUP, index[name]), (GROUP, index["merge"]), EdgeType.FEEDS)
    graph.add_edge((GROUP, index["merge"]), (GROUP, index["prompt"]), EdgeType.FEEDS)
    graph.add_edge((GROUP, index["prompt"]), (GROUP, index["llm"]), EdgeType.FEEDS)
    return {
        "at": at,
        "strategy": result.strategy,
        "nodes": [{"id": f"{GROUP}#{i}", **s} for i, s in enumerate(steps.values())],
        "edges": [
            {"source": f"{GROUP}#{e.source[1]}", "target": f"{GROUP}#{e.target[1]}", "type": e.type.value}
            for e in graph.edges
        ],
    }
