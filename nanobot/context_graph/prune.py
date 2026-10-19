"""Relevance-pruned replay: when the ancestry exceeds a token budget, keep what matters.

Plain replay keeps the newest messages that fit, so an old but relevant turn is lost to
recent small talk. Here the replay is split into turns (a user message plus everything up to
the next one, so tool calls stay with their results); the last few turns are always kept and
older turns compete for the remaining budget by similarity to the current message.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.utils.helpers import estimate_message_tokens

from .embed import Embedder, cosine
from .tree import message_text

Message = Mapping[str, Any]


@dataclass(frozen=True)
class Pruned:
    kept: list[int]  # indices into the input, chronological
    scores: dict[int, float]  # relevance score of each message in a turn kept by relevance


def split_turns(messages: Sequence[Message]) -> list[list[int]]:
    """Indices grouped into turns. Messages before the first user message form their own group."""
    turns: list[list[int]] = []
    for i, m in enumerate(messages):
        if m.get("role") == "user" or not turns:
            turns.append([])
        turns[-1].append(i)
    return turns


def _turn_text(messages: Sequence[Message], turn: Sequence[int]) -> str:
    return "\n".join(
        message_text(messages[i])
        for i in turn
        if messages[i].get("role") in ("user", "assistant") and not is_hidden_history_message(messages[i])
    )


def prune_by_relevance(
    messages: Sequence[Message],
    query: str,
    embedder: Embedder,
    *,
    budget: int,
    keep_recent_turns: int,
    covered: Collection[int] = frozenset(),
) -> Pruned | None:
    """The messages to keep, or ``None`` when everything already fits ``budget`` tokens.

    The last ``keep_recent_turns`` turns are always kept (even if they alone exceed the
    budget). Older turns are ranked by cosine similarity to ``query`` (newest first on ties)
    and added while they fit. Older turns whose messages are all in ``covered`` (indices a
    summary stands in for) are dropped before ranking.
    """
    cost = [estimate_message_tokens(dict(m)) for m in messages]
    if sum(cost) <= budget:
        return None
    turns = split_turns(messages)
    recent = turns[len(turns) - keep_recent_turns :] if keep_recent_turns > 0 else []
    older = turns[: len(turns) - len(recent)]
    used = sum(cost[i] for t in recent for i in t)

    q = embedder.embed(query) if query.strip() else {}
    ranked = sorted(
        (
            (cosine(q, embedder.embed(_turn_text(messages, t))) if q else 0.0, n)
            for n, t in enumerate(older)
            if not all(i in covered for i in t)
        ),
        key=lambda x: (-x[0], -x[1]),
    )
    chosen: dict[int, float] = {}
    for score, n in ranked:
        turn_cost = sum(cost[i] for i in older[n])
        if used + turn_cost <= budget:
            chosen[n] = score
            used += turn_cost

    kept = sorted([i for t in recent for i in t] + [i for n in chosen for i in older[n]])
    scores = {i: chosen[n] for n in chosen for i in older[n]}
    return Pruned(kept, scores)
