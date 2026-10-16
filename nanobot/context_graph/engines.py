from __future__ import annotations

import time
from typing import Any

from loguru import logger

from nanobot.session import Session
from nanobot.utils.helpers import estimate_message_tokens

from .derive import SessionLoader, build_session_graph
from .model import EdgeType
from .observability import ContextResult
from .resolver import get_ancestor_context


class GraphContextEngine:
    """Select history by walking typed ancestor edges instead of replaying one session.

    Budgeting and replay legality are delegated to ``Session.get_history``. Any failure
    falls back to that same linear history for the turn.
    """

    def __init__(self, load_session: SessionLoader | None = None) -> None:
        self.load_session: SessionLoader = load_session or (lambda key: None)

    def build_context(
        self,
        session: Session,
        *,
        max_messages: int = 0,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        **_: Any,
    ) -> ContextResult:
        started = time.perf_counter()
        history_args: dict[str, Any] = {
            "max_messages": max_messages,
            "max_tokens": max_tokens,
            "extend_to_user": extend_to_user,
        }
        node_ids: list[str] = []
        reasons: dict[str, str] = {}
        visited = branch_count = 0
        fallback: str | None = None
        try:
            graph, tip, sessions = build_session_graph(session, self.load_session)
            nodes, node_reasons = get_ancestor_context(graph, tip) if tip is not None else ([], {})
            visited = len(nodes)
            replayable = [(k, i) for k, i in nodes if i >= sessions[k].last_archived]
            replay = Session(
                key=session.key,
                messages=[sessions[k].messages[i] for k, i in replayable],
            )
            history = replay.get_history(**history_args)
            if replayable and not history:
                raise ValueError("graph produced no legal replay")
            kept = replayable[len(replayable) - len(history) :] if history else []
            node_ids = [f"{k}#{i}" for k, i in kept]
            reasons = {f"{k}#{i}": node_reasons[(k, i)] for k, i in kept}
            node_set = set(nodes)
            branch_count = sum(
                1 for e in graph.edges if e.type is EdgeType.BRANCH and e.target in node_set
            )
        except Exception as exc:
            logger.warning("Graph context failed, using linear history: {}", exc)
            fallback = f"{type(exc).__name__}: {exc}"
            history = session.get_history(**history_args)

        return ContextResult(
            strategy="graph",
            messages=history,
            node_ids=node_ids,
            reasons=reasons,
            token_count=sum(estimate_message_tokens(m) for m in history),
            retrieval_ms=(time.perf_counter() - started) * 1000,
            diagnostics={
                "phase": 3,
                "visited": visited,
                "returned": len(history),
                "pruned": max(visited - len(history), 0),
                "branch_count": branch_count,
                "fallback": fallback,
            },
        )
