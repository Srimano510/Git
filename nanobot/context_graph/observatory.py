"""Observatory payload: linear, graph and hybrid contexts rebuilt for the last turn.

The loop only runs the selected strategy, so the comparison is rebuilt on demand from the chat
truncated to before that turn (``_last_turn`` stores the message count, budget and config).
It never feeds the provider, and it is a reconstruction: compaction since the turn can make
it differ from what the model received.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from nanobot.config.schema import ContextGraphConfig
from nanobot.runtime_context import public_history_message
from nanobot.session import Session
from nanobot.utils.helpers import estimate_message_tokens

from .derive import SessionLoader
from .engines import GraphContextEngine
from .observability import ContextResult
from .tree import message_text, turn_anchor

EXCERPT_CHARS = 120
STRATEGIES = ("linear", "graph", "hybrid")


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS] + "…"


def _public(message: Mapping[str, Any]) -> dict[str, Any]:
    return public_history_message(message)


def build_observatory(
    key: str,
    load_session: SessionLoader,
    list_sessions: Callable[[], Sequence[Mapping[str, Any]]],
) -> dict[str, Any] | None:
    """Sanitized comparison for the last recorded turn of ``key``; ``None`` if there is none."""
    session = load_session(key)
    if session is None:
        return None
    turn = cast(object, session.metadata.get("_last_turn"))
    if not isinstance(turn, dict):
        return None
    record = cast(dict[str, Any], turn)
    at = record.get("at")
    anchor = turn_anchor(session, at) if isinstance(at, int) and at >= 0 else None
    if anchor is None:
        return None
    assert isinstance(at, int)
    query = message_text(_public(session.messages[int(anchor.rpartition("#")[2])]))

    snapshot = Session(
        key=key,
        messages=session.messages[:at],
        metadata=dict(session.metadata),
        last_consolidated=min(session.last_consolidated, at),
    )
    sessions: dict[str, Session] = {key: snapshot}

    def get(k: str) -> Session | None:
        if k not in sessions and (loaded := load_session(k)) is not None:
            sessions[k] = loaded
        return sessions.get(k)

    try:
        config = ContextGraphConfig.model_validate(record.get("graph_config") or {})
    except ValueError:
        config = ContextGraphConfig()
    max_tokens = record.get("max_tokens")
    max_tokens = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else 0
    engine = GraphContextEngine(load_session=get, list_sessions=list_sessions, config=config)
    pool = snapshot.metadata.get("context_pool")

    estimate_message_tokens({"content": "warm up"})  # first call loads the tokenizer; not a strategy's cost
    ids: dict[str, list[str]] = {}
    reasons: dict[str, dict[str, str]] = {}
    strategies: dict[str, dict[str, Any]] = {}
    for name in STRATEGIES:
        started = time.perf_counter()
        info: dict[str, Any] = {"nodes": 0, "tokens": 0, "ms": 0.0, "fallback": None}
        ids[name], reasons[name] = [], {}
        try:
            if name == "linear":
                history = snapshot.get_history()
                usable = [i for i, m in enumerate(snapshot.messages) if not m.get("_command")]
                ids[name] = [f"{key}#{i}" for i in usable[len(usable) - len(history) :]]
                reasons[name] = {n: "history" for n in ids[name]}
                tokens = sum(estimate_message_tokens(m) for m in history)
                ms = (time.perf_counter() - started) * 1000
                info.update(nodes=len(history), tokens=tokens, ms=ms, timing=(ms, 0.0))
            else:
                result: ContextResult = engine.build_context(
                    snapshot, max_tokens=max_tokens, query=query,
                    hybrid=name == "hybrid", pool=pool if isinstance(pool, str) else None,
                )
                diag = result.diagnostics
                ids[name], reasons[name] = list(result.node_ids), dict(result.reasons)
                vector = float(diag.get("embed_ms") or 0.0)
                tokens = result.token_count + (
                    estimate_message_tokens({"content": result.recalled}) if result.recalled else 0
                )
                info.update(
                    nodes=len(result.node_ids) or len(result.messages), tokens=tokens, ms=result.retrieval_ms,
                    timing=(result.retrieval_ms - vector, vector),
                    fallback=diag.get("fallback") or diag.get("semantic_error"),
                )
                info["pruned"] = int(diag.get("pruned_by_relevance") or 0)
                if diag.get("embedder"):
                    info["embedder"] = diag["embedder"]
                if name == "hybrid":
                    info["recalled"] = int(diag.get("semantic_included") or 0)
                    info["summaries"] = int(diag.get("summaries_used") or 0)
        except Exception as exc:
            info.update(fallback=f"{type(exc).__name__}: {exc}", timing=(0.0, 0.0))
        traversal, vector = info.pop("timing")
        info["timing"] = {
            "traversal_ms": round(traversal, 1),
            "vector_ms": round(vector, 1),
            "total_ms": round(info["ms"], 1),
        }
        info["ms"] = round(info["ms"], 1)
        strategies[name] = info

    nodes: list[dict[str, Any]] = []
    for node_id in sorted({n for name in STRATEGIES for n in ids[name]}, key=_sort_key):
        owner_key, _, index = node_id.rpartition("#")
        owner = get(owner_key)
        if owner is None or not index.isdigit() or int(index) >= len(owner.messages):
            continue
        message = _public(owner.messages[int(index)])
        nodes.append({
            "id": node_id,
            "role": message.get("role"),
            "excerpt": _excerpt(message_text(message)),
            "tokens": estimate_message_tokens(message),
            "in": {name: node_id in ids[name] for name in STRATEGIES},
            "reason": {name: reasons[name][node_id] for name in STRATEGIES if node_id in reasons[name]},
        })
    only = {
        name: sum(1 for n in nodes if n["in"][name] and sum(n["in"].values()) == 1)
        for name in STRATEGIES
    }
    selected = record.get("strategy")
    return {
        "at": at,
        "selected": selected if selected in STRATEGIES else None,
        "reconstructed": True,
        "query": _excerpt(query),
        "strategies": strategies,
        "nodes": nodes,
        "only": only,
    }


def _sort_key(node_id: str) -> tuple[str, int]:
    key, _, index = node_id.rpartition("#")
    return key, int(index) if index.isdigit() else 0
