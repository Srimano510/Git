from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.session import Session
from nanobot.utils.helpers import estimate_message_tokens, truncate_text_to_tokens

from .derive import SessionLoader, build_session_graph
from .embed import Embedder, HashEmbedder
from .model import EdgeType, NodeId
from .observability import ContextResult
from .recall import pool_candidates, recall
from .resolver import get_ancestor_context
from .summaries import usable_summaries
from .tree import load_family, message_text

if TYPE_CHECKING:
    from nanobot.config.schema import ContextGraphConfig


class GraphContextEngine:
    """Select history by walking typed ancestor edges instead of replaying one session.

    Budgeting and replay legality are delegated to ``Session.get_history``. Any failure
    falls back to that same linear history for the turn. In ``hybrid`` mode, messages
    outside the replayed history that match the query (and summaries standing in for
    dropped ranges) are returned separately as ``ContextResult.recalled``.
    """

    def __init__(
        self,
        load_session: SessionLoader | None = None,
        *,
        list_sessions: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
        embedder: Embedder | None = None,
        config: ContextGraphConfig | None = None,
    ) -> None:
        from nanobot.config.schema import ContextGraphConfig

        self.load_session: SessionLoader = load_session or (lambda key: None)
        self.list_sessions: Callable[[], Sequence[Mapping[str, Any]]] = (
            list_sessions or (lambda: ())
        )
        self.embedder: Embedder = embedder or HashEmbedder()
        self.config = config or ContextGraphConfig()

    def build_context(
        self,
        session: Session,
        *,
        max_messages: int = 0,
        max_tokens: int = 0,
        extend_to_user: bool = False,
        query: str | None = None,
        hybrid: bool = False,
        pool: str | None = None,
        **_: Any,
    ) -> ContextResult:
        started = time.perf_counter()
        history_args: dict[str, Any] = {
            "max_messages": max_messages,
            "max_tokens": max_tokens,
            "extend_to_user": extend_to_user,
        }
        if hybrid and max_tokens:  # leave room for the recalled block
            history_args["max_tokens"] = max_tokens - min(
                self.config.recall_token_budget, max_tokens // 2
            )
        node_ids: list[str] = []
        reasons: dict[str, str] = {}
        visited = branch_count = 0
        fallback: str | None = None
        recalled = ""
        recall_info: dict[str, Any] = {}
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
            if hybrid:
                recalled, recall_info = self._recall(
                    session, sessions, nodes, set(kept), query, pool, node_ids, reasons
                )
        except Exception as exc:
            logger.warning("Graph context failed, using linear history: {}", exc)
            fallback = f"{type(exc).__name__}: {exc}"
            history = session.get_history(**history_args)

        return ContextResult(
            strategy="hybrid" if hybrid else "graph",
            messages=history,
            node_ids=node_ids,
            reasons=reasons,
            token_count=sum(estimate_message_tokens(m) for m in history),
            retrieval_ms=(time.perf_counter() - started) * 1000,
            recalled=recalled,
            diagnostics={
                "phase": 4 if hybrid else 3,
                "visited": visited,
                "returned": len(history),
                "pruned": max(visited - len(history), 0),
                "branch_count": branch_count,
                "fallback": fallback,
                **recall_info,
            },
        )

    def _recall(
        self,
        session: Session,
        sessions: dict[str, Session],
        ancestry: Sequence[NodeId],
        kept: set[NodeId],
        query: str | None,
        pool: str | None,
        node_ids: list[str],
        reasons: dict[str, str],
    ) -> tuple[str, dict[str, Any]]:
        """Summaries and similar messages that are not in the replay. Never raises."""
        pool = pool or self.config.semantic_pool
        info: dict[str, Any] = {"pool": pool}
        started = time.perf_counter()
        text = ""
        try:
            if query is None:
                query = next(
                    (message_text(m) for m in reversed(session.messages) if m.get("role") == "user"),
                    "",
                )
            family = None
            known = {**sessions}
            if pool == "family":
                family = load_family(session.key, self.list_sessions(), self.load_session)
                if family is not None:
                    known = {**family.sessions, **sessions}
            cfg = self.config
            summaries = usable_summaries(known, ancestry, kept)
            covered = {(u.key, i) for u in summaries for i in range(u.start, u.end + 1)}
            candidates = pool_candidates(pool, ancestry, kept, known, family)
            info["semantic_candidates"] = len(candidates)
            hits = recall(
                query,
                [(n, m) for n, m in candidates if n not in covered],
                self.embedder,
                top_k=cfg.semantic_top_k,
                min_score=cfg.semantic_min_score,
            )
            info["semantic_hits"] = len(hits)

            lines: list[tuple[str, str, str]] = []  # (node id, reason, rendered line)
            for u in summaries:
                lines.append((
                    f"{u.key}#{u.start}",
                    f"summary (covers {u.start}-{u.end})",
                    f"[summary of messages {u.start}-{u.end}] {u.text}",
                ))
            for h in hits:
                role = known[h.node[0]].messages[h.node[1]].get("role")
                lines.append((
                    f"{h.node[0]}#{h.node[1]}",
                    f"vector (score {h.score:.2f})",
                    f"[{role}, similarity {h.score:.2f}] {h.text}",
                ))

            used: list[str] = []
            included = {"vector": 0, "summary": 0}
            remaining = cfg.recall_token_budget
            for nid, reason, line in lines:
                if remaining <= 0:
                    break
                line = truncate_text_to_tokens(line, remaining)
                remaining -= estimate_message_tokens({"content": line})
                used.append(line)
                node_ids.append(nid)
                reasons[nid] = reason
                included[reason.split(" ", 1)[0]] += 1
            info["semantic_included"] = included["vector"]
            info["summaries_used"] = included["summary"]
            if used:
                text = (
                    "Earlier context retrieved by similarity or summary. It is not part of the "
                    "recent messages and may come from outside this conversation branch:\n"
                    + "\n".join(used)
                )
        except Exception as exc:
            logger.warning("Semantic recall skipped: {}", exc)
            info["semantic_error"] = f"{type(exc).__name__}: {exc}"
            text = ""
        info["embed_ms"] = (time.perf_counter() - started) * 1000
        return text, info
