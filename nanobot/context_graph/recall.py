"""Semantic recall: rank past messages that are not in the replayed history."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nanobot.session import Session
from nanobot.session.history_visibility import is_hidden_history_message

from .embed import Embedder, cosine
from .model import NodeId
from .tree import Family, message_text

Message = Mapping[str, Any]


@dataclass(frozen=True)
class Hit:
    node: NodeId
    score: float
    text: str


def recall(
    query: str,
    candidates: Iterable[tuple[NodeId, Message]],
    embedder: Embedder,
    *,
    top_k: int = 3,
    min_score: float = 0.15,
    exclude: frozenset[NodeId] | set[NodeId] = frozenset(),
) -> list[Hit]:
    """Top ``top_k`` user/assistant text messages scoring at least ``min_score``.

    Tool results, hidden history, slash-command turns, empty text and ``exclude`` nodes never qualify.
    """
    q = embedder.embed(query)
    if not q:
        return []
    hits: list[Hit] = []
    for node, m in candidates:
        if node in exclude or m.get("role") not in ("user", "assistant") or m.get("_command"):
            continue
        if is_hidden_history_message(m) or not (text := message_text(m).strip()):
            continue
        if (score := cosine(q, embedder.embed(text))) >= min_score:
            hits.append(Hit(node, score, text))
    hits.sort(key=lambda h: (-h.score, h.node))
    return hits[:top_k]


def pool_candidates(
    pool: str,
    ancestry: Sequence[NodeId],
    kept: set[NodeId],
    sessions: Mapping[str, Session],
    family: Family | None,
) -> list[tuple[NodeId, Message]]:
    """Messages semantic search may bring back.

    ``archived``: this chat's own ancestry that did not make it into the replay (compacted
    or budget-pruned). ``family``: additionally every other branch of the chat family.
    """
    nodes = [n for n in ancestry if n not in kept]
    if pool == "family" and family is not None:
        seen = set(ancestry)
        nodes += sorted(n for n in family.nodes if n not in seen)
    out: list[tuple[NodeId, Message]] = []
    for key, i in nodes:
        owner = sessions.get(key)
        if owner is not None and i < len(owner.messages):
            out.append(((key, i), owner.messages[i]))
    return out
