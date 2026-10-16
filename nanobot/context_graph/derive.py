"""Derive the typed-edge DAG from sessions already persisted by SessionManager.

REPLY edges are message order, BRANCH edges come from fork metadata written when a
session is forked, CONTEXT edges from ``session.metadata["context_edges"]``. A fork's
copied prefix aliases the source session's nodes, so ancestry continues through the
source (and its own source) rather than the child's copy.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from nanobot.session import Session

from .model import ConversationGraph, EdgeType, NodeId

FORK_SOURCE_KEY = "context_graph_source_session_key"
FORK_CHILD_KEY = "context_graph_child_session_key"
FORK_BOUNDARY_KEY = "context_graph_fork_boundary"
CONTEXT_EDGES_KEY = "context_edges"

SessionLoader = Callable[[str], Session | None]


def build_session_graph(
    session: Session, load_session: SessionLoader
) -> tuple[ConversationGraph, NodeId | None, dict[str, Session]]:
    """Return the graph, the tip node of ``session`` and every session it touched."""
    sessions = {session.key: session}

    def get(key: str) -> Session:
        if key not in sessions:
            loaded = load_session(key)
            if loaded is None:
                raise LookupError(f"session {key!r} not found")
            sessions[key] = loaded
        return sessions[key]

    def fork(s: Session) -> tuple[str, int] | None:
        meta: dict[str, Any] = s.metadata
        source, boundary = meta.get(FORK_SOURCE_KEY), meta.get(FORK_BOUNDARY_KEY)
        if (
            meta.get(FORK_CHILD_KEY) == s.key
            and isinstance(source, str)
            and isinstance(boundary, int)
            and not isinstance(boundary, bool)
            and 0 < boundary <= len(s.messages)
        ):
            return source, boundary
        return None

    def owner(key: str, index: int) -> NodeId:
        while (f := fork(get(key))) and index < f[1]:
            key = f[0]
        return key, index

    graph = ConversationGraph()
    pending: list[str] = [session.key]
    seen: set[str] = set()
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        s = get(key)
        f = fork(s)
        for i in range((f[1] if f else 0) + 1, len(s.messages)):
            graph.add_edge((key, i - 1), (key, i), EdgeType.REPLY)
        if f:
            if len(s.messages) > f[1]:
                graph.add_edge(owner(f[0], f[1] - 1), (key, f[1]), EdgeType.BRANCH)
            pending.append(f[0])
        edges = cast(list[dict[str, tuple[str, int]]], s.metadata.get(CONTEXT_EDGES_KEY) or [])
        for edge in edges:
            (src_key, src_index), (dst_key, dst_index) = edge["source"], edge["target"]
            graph.add_edge(owner(src_key, src_index), owner(dst_key, dst_index), EdgeType.CONTEXT)
            pending.append(src_key)

    tip = owner(session.key, len(session.messages) - 1) if session.messages else None
    return graph, tip, sessions
