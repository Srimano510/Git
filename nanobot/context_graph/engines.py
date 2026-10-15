from abc import ABC, abstractmethod
from typing import Any
import time
from loguru import logger
from nanobot.session import Session
from nanobot.context_graph.model import ConversationGraph
from nanobot.context_graph.observability import ContextResult
from nanobot.context_graph.store import ContextGraphStore, _default_graph_store
from nanobot.context_graph.sync import _sync_session_graph
from nanobot.utils.helpers import estimate_message_tokens
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

        if kwargs.get("persist_graph", True):
            graph_store = store or _default_graph_store()
            try:
                graph_obj, _, graph_sync_ms, _ = _sync_session_graph(session, graph_store, graph)
                branch_count = graph_obj.branch_count()
            except Exception as exc:
                logger.warning("Non-fatal graph sync failure in LinearContextEngine: {}", exc)

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
    Experimental graph-based context engine.

    Phase 1 preserves chronological session replay while synchronizing the
    conversation graph for persistence and branching diagnostics.
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
        effective_max = max_messages or self.window_size
        graph_store = store or _default_graph_store()
        graph_obj: ConversationGraph | None = None
        graph_sync_ms = 0.0
        branches_added = 0
        node_ids: list[str] = []
        if kwargs.get("persist_graph", True):
            try:
                graph_obj, node_ids, graph_sync_ms, branches_added = _sync_session_graph(
                    session,
                    graph_store,
                    graph,
                )
            except Exception as exc:
                logger.warning("Graph sync failed in GraphContextEngine: {}", exc)

        result = self._fallback_engine.build_context(
            session,
            max_messages=max_messages,
            max_tokens=max_tokens,
            extend_to_user=extend_to_user,
            graph=graph,
            store=graph_store,
            persist_graph=False,
            **{key: value for key, value in kwargs.items() if key != "persist_graph"},
        )
        return ContextResult(
            strategy="graph",
            messages=result.messages,
            node_ids=node_ids,
            reasons={node_id: "phase1_linear_baseline" for node_id in node_ids},
            token_count=result.token_count,
            retrieval_ms=result.retrieval_ms,
            diagnostics={
                "phase": 1,
                "mode": "graph_baseline_delegation",
                "total_graph_nodes": len(graph_obj.nodes) if graph_obj is not None else 0,
                "retrieved_messages": len(result.messages),
                "branch_count": graph_obj.branch_count() if graph_obj is not None else 0,
                "branches_added": branches_added,
                "graph_sync_ms": graph_sync_ms,
                "window_size": effective_max,
            },
        )


def get_context_engine(strategy: str = "linear", **kwargs: Any) -> ContextEngineBase:
    """Create the configured context engine, defaulting to chronological replay."""
    normalized = (strategy or "").strip().lower()
    if normalized in {"graph", "context_graph"}:
        return GraphContextEngine(**kwargs)
    return LinearContextEngine(**kwargs)