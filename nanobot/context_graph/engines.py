"""Context Engine implementations for Linear and Graph context construction."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.context_graph.model import ConversationGraph
from nanobot.context_graph.observability import ContextResult
from nanobot.context_graph.store import ContextGraphStore, get_context_graph_store
from nanobot.utils.helpers import estimate_message_tokens

if TYPE_CHECKING:
    from nanobot.session.manager import Session


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

        # Optionally synchronize session messages into the graph store for persistence
        if store is not None or kwargs.get("persist_graph", True):
            graph_store = store or get_context_graph_store()
            try:
                graph_obj = graph_store.sync_session_messages(session.key, session.messages, graph)
                graph_store.save_graph(session.key, graph_obj)
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

        graph_store = store or get_context_graph_store()
        try:
            graph_obj = graph_store.sync_session_messages(session.key, session.messages, graph)
            graph_store.save_graph(session.key, graph_obj)
            node_ids = list(graph_obj.nodes.keys())
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
                "total_graph_nodes": len(node_ids),
                "retrieved_messages": len(result.messages),
            },
        )


def get_context_engine(strategy: str = "linear", **kwargs: Any) -> ContextEngineBase:
    """Factory helper to obtain a ContextEngine by strategy name."""
    normalized = (strategy or "").strip().lower()
    if normalized in {"graph", "context_graph"}:
        return GraphContextEngine(**kwargs)
    return LinearContextEngine(**kwargs)
