"""Observatory payload: linear, graph and hybrid contexts compared for one turn.

``compare`` builds all three from the chat as it was before the turn. The loop calls it right
after building the real context (``real`` carries what the turn actually used, so that
strategy's numbers are the actual ones) and stores the result in ``_last_turn["comparison"]``;
that recording is exact. ``build_observatory`` serves the recording, or, for turns recorded
without it, rebuilds the comparison from the chat truncated to before the turn, a
reconstruction that compaction since the turn can make drift. The comparison never feeds the
provider.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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
MAX_NODES = 120  # nodes listed per comparison; counts and tokens always cover every node
STRATEGIES = ("linear", "graph", "hybrid")

Listing = Callable[[], Sequence[Mapping[str, Any]]]


@dataclass
class Real:
    """What the turn actually used, so that strategy is not recomputed."""

    strategy: str
    history: list[dict[str, Any]]
    ms: float
    result: ContextResult | None = None  # graph/hybrid only


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS] + "…"


def _public(message: Mapping[str, Any]) -> dict[str, Any]:
    return public_history_message(message)


def _sort_key(node_id: str) -> tuple[str, int]:
    key, _, index = node_id.rpartition("#")
    return key, int(index) if index.isdigit() else 0


def _linear(
    snapshot: Session, history: list[dict[str, Any]], ms: float
) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    usable = [i for i, m in enumerate(snapshot.messages) if not m.get("_command")]
    ids = [f"{snapshot.key}#{i}" for i in usable[len(usable) - len(history) :]]
    info: dict[str, Any] = {
        "nodes": len(history),
        "tokens": sum(estimate_message_tokens(m) for m in history),
        "ms": ms,
        "timing": (ms, 0.0),
        "fallback": None,
    }
    return ids, {n: "history" for n in ids}, info


def _from_result(
    result: ContextResult, hybrid: bool
) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    diag = result.diagnostics
    vector = float(diag.get("embed_ms") or 0.0)
    info: dict[str, Any] = {
        "nodes": len(result.node_ids) or len(result.messages),
        "tokens": result.token_count
        + (estimate_message_tokens({"content": result.recalled}) if result.recalled else 0),
        "ms": result.retrieval_ms,
        "timing": (result.retrieval_ms - vector, vector),
        "fallback": diag.get("fallback") or diag.get("semantic_error"),
        "pruned": int(diag.get("pruned_by_relevance") or 0),
    }
    if diag.get("embedder"):
        info["embedder"] = diag["embedder"]
    if hybrid:
        info["recalled"] = int(diag.get("semantic_included") or 0)
        info["summaries"] = int(diag.get("summaries_used") or 0)
    return list(result.node_ids), dict(result.reasons), info


def compare(
    snapshot: Session,
    query: str,
    record: Mapping[str, Any],
    load_session: SessionLoader,
    list_sessions: Listing,
    *,
    real: Real | None = None,
    max_nodes: int = MAX_NODES,
) -> dict[str, Any]:
    """Sanitized comparison of the three strategies for ``query`` on ``snapshot``.

    ``snapshot`` is the chat as it was before the turn; ``record`` is ``_last_turn`` (budget,
    graph config, selected strategy). With ``real`` the payload is marked as recorded.
    """
    key = snapshot.key
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
        ids[name], reasons[name] = [], {}
        info: dict[str, Any] = {"nodes": 0, "tokens": 0, "ms": 0.0, "fallback": None}
        try:
            if real is not None and real.strategy == name and name == "linear":
                ids[name], reasons[name], info = _linear(snapshot, real.history, real.ms)
            elif real is not None and real.strategy == name and real.result is not None:
                ids[name], reasons[name], info = _from_result(real.result, name == "hybrid")
            elif name == "linear":
                started = time.perf_counter()
                history = snapshot.get_history()
                ids[name], reasons[name], info = _linear(
                    snapshot, history, (time.perf_counter() - started) * 1000
                )
            else:
                result = engine.build_context(
                    snapshot, max_tokens=max_tokens, query=query,
                    hybrid=name == "hybrid", pool=pool if isinstance(pool, str) else None,
                )
                ids[name], reasons[name], info = _from_result(result, name == "hybrid")
        except Exception as exc:
            info = {**info, "fallback": f"{type(exc).__name__}: {exc}", "timing": (0.0, 0.0)}
        traversal, vector = info.pop("timing", (0.0, 0.0))
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
    omitted = 0
    if len(nodes) > max_nodes:  # keep what differs between strategies; drop shared nodes first
        differs = [n for n in nodes if len(set(n["in"].values())) > 1]
        shared = [n for n in nodes if len(set(n["in"].values())) == 1]
        kept = (differs + shared)[:max_nodes]
        omitted = len(nodes) - len(kept)
        nodes = sorted(kept, key=lambda n: _sort_key(n["id"]))
    selected = record.get("strategy")
    return {
        "at": record.get("at", len(snapshot.messages)),
        "selected": selected if selected in STRATEGIES else None,
        "reconstructed": real is None,
        "query": _excerpt(query),
        "strategies": strategies,
        "nodes": nodes,
        "only": only,
        "omitted": omitted,
    }


def build_observatory(
    key: str,
    load_session: SessionLoader,
    list_sessions: Listing,
) -> dict[str, Any] | None:
    """The comparison for the last turn of ``key``: the recording if there is one, else a rebuild.

    ``None`` when no turn was recorded or its user message is gone.
    """
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

    recorded = record.get("comparison")
    if isinstance(recorded, dict) and cast(dict[str, Any], recorded).get("at") == at:
        return cast(dict[str, Any], recorded)

    query = message_text(_public(session.messages[int(anchor.rpartition("#")[2])]))
    snapshot = Session(
        key=key,
        messages=session.messages[:at],
        metadata=dict(session.metadata),
        last_consolidated=min(session.last_consolidated, at),
    )
    return compare(snapshot, query, record, load_session, list_sessions)
