"""Context Engine implementations for Linear and Graph context construction."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.context_graph.model import ConversationGraph
from nanobot.context_graph.observability import ContextResult
from nanobot.context_graph.store import ContextGraphStore
from nanobot.context_graph.sync import (
    FORK_BOUNDARY_METADATA_KEY,
    FORK_CHILD_SESSION_METADATA_KEY,
    FORK_SOURCE_SESSION_METADATA_KEY,
    GRAPH_ID_METADATA_KEY,
    graph_id_for_session,
    synchronize_session,
)
from nanobot.utils.helpers import estimate_message_tokens

if TYPE_CHECKING:
    from nanobot.session.manager import Session


_SESSION_GRAPH_NAMESPACE = "sessions"


def _default_graph_store() -> ContextGraphStore:
    return ContextGraphStore(root=get_data_dir() / "context_graph")


def _sync_session_graph(
    session: Session,
    store: ContextGraphStore,
    graph: ConversationGraph | None = None,
) -> tuple[ConversationGraph, list[str], float, int]:
    sync_started = time.perf_counter()
    graph_id = graph.graph_id if graph is not None else session.metadata.get(GRAPH_ID_METADATA_KEY)
    if not isinstance(graph_id, str) or not graph_id:
        graph_id = graph_id_for_session(session.key)
    graph_obj = graph or store.load(_SESSION_GRAPH_NAMESPACE, graph_id)
    if graph_obj is None:
        graph_obj = ConversationGraph(graph_id=graph_id)
    branch_count_before = graph_obj.branch_count()

    source_session = session.metadata.get(FORK_SOURCE_SESSION_METADATA_KEY)
    child_session = session.metadata.get(FORK_CHILD_SESSION_METADATA_KEY)
    fork_boundary = session.metadata.get(FORK_BOUNDARY_METADATA_KEY)
    if child_session != session.key:
        source_session = None
        fork_boundary = None

    nodes = synchronize_session(
        graph_obj,
        session_key=session.key,
        messages=session.messages,
        source_session=source_session if isinstance(source_session, str) else None,
        fork_boundary=fork_boundary if isinstance(fork_boundary, int) else None,
    )
    saved_path = store.save(graph_obj, _SESSION_GRAPH_NAMESPACE)
    sync_ms = (time.perf_counter() - sync_started) * 1000
    branches_added = graph_obj.branch_count() - branch_count_before
    if saved_path is None:
        logger.warning("Context graph persistence failed for graph {}", graph_obj.graph_id)
    if branches_added:
        logger.info(
            "Added {} context-graph branch edge(s); total={}, sync_ms={:.2f}",
            branches_added,
            graph_obj.branch_count(),
            sync_ms,
        )
    return graph_obj, [node.id for node in nodes], sync_ms, branches_added


class ContextEngineBase(ABC):
    """Abstract base class for conversation context engines."""

    @abstractmethod
    def build_context(
        self,
        session: Session,
        *,
        max_messages: int = 0,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        graph: ConversationGraph | None = None,
        store: ContextGraphStore | None = None,
        **kwargs: Any,
    ) -> ContextResult:
        """Build and return the prompt conversation context for the upcoming turn."""
        raise NotImplementedError


class LinearContextEngine(ContextEngineBase):
    """
    Baseline context engine that uses chronological session replay history.
    Preserves legal nanobot replay semantics, tool calls, and compaction boundaries.
    """

    def __init__(self, window_size: int = 0) -> None:
        self.window_size = window_size

    def build_context(
        self,
        session: Session,
        *,
        max_messages: int = 0,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        graph: ConversationGraph | None = None,
        store: ContextGraphStore | None = None,
        **kwargs: Any,
    ) -> ContextResult:
        started = time.perf_counter()
        effective_max = max_messages or self.window_size

        history = session.get_history(
            max_messages=effective_max,
            max_tokens=max_tokens,
            extend_to_user=extend_to_user,
        )

        token_count = sum(estimate_message_tokens(msg) for msg in history)
        elapsed_ms = (time.perf_counter() - started) * 1000
        graph_sync_ms = 0.0
        branch_count = 0

        # Optionally synchronize session messages into the graph store for persistence
        if kwargs.get("persist_graph", True):
            graph_store = store or _default_graph_store()
            try:
                graph_obj, _, graph_sync_ms, _ = _sync_session_graph(session, graph_store, graph)
                branch_count = graph_obj.branch_count()
            except Exception as exc:
                logger.debug("Non-fatal graph sync failure in LinearContextEngine: {}", exc)

        return ContextResult(
            strategy="linear",
            messages=history,
            node_ids=[],
            reasons={},
            token_count=token_count,
            retrieval_ms=elapsed_ms,
            diagnostics={
                "message_count": len(history),
                "window_size": effective_max,
                "branch_count": branch_count,
                "graph_sync_ms": graph_sync_ms,
            },
        )


class GraphContextEngine(ContextEngineBase):
    """
    Experimental Graph-based context engine.
    In Phase 1, acts as an adapter around the baseline replay semantics while
    maintaining and synchronizing the graph data model.
    """

    def __init__(self, window_size: int = 0) -> None:
        self.window_size = window_size
        self._fallback_engine = LinearContextEngine(window_size=window_size)

    def build_context(
        self,
        session: Session,
        *,
        max_messages: int = 0,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        graph: ConversationGraph | None = None,
        store: ContextGraphStore | None = None,
        **kwargs: Any,
    ) -> ContextResult:
        started = time.perf_counter()
        logger.debug("Using GraphContextEngine (Phase 1 baseline delegation)")

        graph_store = store or _default_graph_store()
        graph_obj: ConversationGraph | None = None
        graph_sync_ms = 0.0
        branches_added = 0
        try:
            graph_obj, node_ids, graph_sync_ms, branches_added = _sync_session_graph(
                session,
                graph_store,
                graph,
            )
        except Exception as exc:
            logger.warning("Graph sync failed in GraphContextEngine: {}", exc)
            node_ids = []

        # Delegate to linear history retrieval for Phase 1 baseline
        result = self._fallback_engine.build_context(
            session,
            max_messages=max_messages,
            max_tokens=max_tokens,
            extend_to_user=extend_to_user,
            graph=graph,
            store=graph_store,
            persist_graph=False,
            **kwargs,
        )

        elapsed_ms = (time.perf_counter() - started) * 1000

        return ContextResult(
            strategy="graph",
            messages=result.messages,
            node_ids=node_ids,
            reasons={nid: "phase1_linear_baseline" for nid in node_ids},
            token_count=result.token_count,
            retrieval_ms=elapsed_ms,
            diagnostics={
                "phase": 1,
                "mode": "graph_baseline_delegation",
                "total_graph_nodes": len(graph_obj.nodes) if graph_obj is not None else 0,
                "retrieved_messages": len(result.messages),
                "branch_count": graph_obj.branch_count() if graph_obj is not None else 0,
                "branches_added": branches_added,
                "graph_sync_ms": graph_sync_ms,
            },
        )


def get_context_engine(strategy: str = "linear", **kwargs: Any) -> ContextEngineBase:
    """Factory helper to obtain a ContextEngine by strategy name."""
    normalized = (strategy or "").strip().lower()
    if normalized in {"graph", "context_graph"}:
        return GraphContextEngine(**kwargs)
    return LinearContextEngine(**kwargs)
