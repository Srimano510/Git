"""Manual summaries of message ranges, stored in session metadata (like ``context_edges``)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from nanobot.session import Session

from .model import NodeId

SUMMARIES_KEY = "context_summaries"


@dataclass(frozen=True)
class Summary:
    key: str
    start: int
    end: int
    text: str


def list_summaries(session: Session) -> list[dict[str, Any]]:
    raw = cast(object, session.metadata.get(SUMMARIES_KEY))
    items = cast(list[object], raw) if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        d = cast(dict[str, Any], item)
        start, end, text = d.get("from"), d.get("to"), d.get("text")
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and isinstance(text, str)
            and text
        ):
            out.append({"from": start, "to": end, "text": text})
    return out


def add_summary(session: Session, start: int, end: int, text: str) -> None:
    """Summarise messages ``start..end`` (inclusive, indices into this session)."""
    text = text.strip()
    if not text:
        raise ValueError("summary text is empty")
    if not 0 <= start <= end < len(session.messages):
        raise ValueError(f"range {start}-{end} is outside 0-{len(session.messages) - 1}")
    session.metadata[SUMMARIES_KEY] = [*list_summaries(session), {"from": start, "to": end, "text": text}]


def clear_summaries(session: Session) -> int:
    removed = len(list_summaries(session))
    session.metadata.pop(SUMMARIES_KEY, None)
    return removed


def usable_summaries(
    sessions: Mapping[str, Session], ancestry: Sequence[NodeId], kept: set[NodeId]
) -> list[Summary]:
    """Summaries that stand in for ancestry nodes: every covered node was dropped from replay."""
    in_ancestry = set(ancestry)
    out: list[Summary] = []
    for key, s in sessions.items():
        for d in list_summaries(s):
            covered = {(key, i) for i in range(d["from"], d["to"] + 1)} & in_ancestry
            if covered and not covered & kept:
                out.append(Summary(key, d["from"], d["to"], d["text"]))
    return sorted(out, key=lambda u: (u.key, u.start))
