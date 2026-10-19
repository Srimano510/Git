"""Manual ``CONTEXT`` links: feed a message of another chat (and its ancestry) into this one.

Links live in ``session.metadata["context_edges"]``, the list ``derive.py`` already reads, so
graph and hybrid context pick them up with no other change. Every failure raises ``ValueError``
with a message that is shown to the user as is; nothing is stored on failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from nanobot.session import Session

from .derive import CONTEXT_EDGES_KEY, SessionLoader, build_session_graph, canonical_node
from .model import NodeId
from .resolver import get_ancestor_context

MAX_LINKS = 20  # per chat: keeps the DAG and the session file small


@dataclass(frozen=True)
class Link:
    number: int  # 1-based position in the chat's list; what ``/context unlink`` takes
    source: NodeId
    target: NodeId


def parse_node(text: str) -> NodeId:
    """``<chat key>#<message number>`` -> ``(key, number)``; the key keeps its case."""
    key, sep, index = text.strip().rpartition("#")
    if not sep or not key or not index.isdigit():
        raise ValueError(f"`{text}` is not a message id; use `<chat key>#<message number>`")
    return key, int(index)


def _node(raw: object) -> NodeId | None:
    if isinstance(raw, list | tuple) and len(cast(list[object], raw)) == 2:
        key, index = cast(list[object], raw)
        if isinstance(key, str) and isinstance(index, int) and not isinstance(index, bool):
            return key, index
    return None


def list_links(session: Session) -> list[Link]:
    raw = cast(object, session.metadata.get(CONTEXT_EDGES_KEY))
    out: list[Link] = []
    for item in cast(list[object], raw) if isinstance(raw, list) else []:
        if isinstance(item, dict):
            d = cast(dict[str, object], item)
            source, target = _node(d.get("source")), _node(d.get("target"))
            if source is not None and target is not None:
                out.append(Link(len(out) + 1, source, target))
    return out


def _store(session: Session, links: list[Link]) -> None:
    if links:
        session.metadata[CONTEXT_EDGES_KEY] = [
            {"source": list(link.source), "target": list(link.target)} for link in links
        ]
    else:
        session.metadata.pop(CONTEXT_EDGES_KEY, None)


def add_link(
    session: Session, source: NodeId, target: int | None, load_session: SessionLoader
) -> Link:
    """Link ``source`` into message ``target`` of ``session`` (default: its latest non-command message)."""
    sessions: dict[str, Session] = {session.key: session}

    def get(key: str) -> Session | None:
        if key not in sessions and (loaded := load_session(key)) is not None:
            sessions[key] = loaded
        return sessions.get(key)

    owner = get(source[0])
    if owner is None:
        raise ValueError(f"chat `{source[0]}` was not found")
    latest = next((i for i in range(len(session.messages) - 1, -1, -1) if not session.messages[i].get("_command")), None)
    if latest is None:  # empty, or nothing but slash-command turns
        raise ValueError("this chat has no messages yet, so there is nothing to link into")
    if not 0 <= source[1] < len(owner.messages):
        raise ValueError(f"message {source[1]} is out of range for `{source[0]}` (0-{len(owner.messages) - 1})")
    to = latest if target is None else target
    if not 0 <= to < len(session.messages):
        raise ValueError(f"message {to} is out of range for this chat (0-{len(session.messages) - 1})")
    if owner.messages[source[1]].get("_command") or session.messages[to].get("_command"):
        raise ValueError("slash-command messages cannot be linked")

    links = list_links(session)
    if len(links) >= MAX_LINKS:
        raise ValueError(f"a chat can have at most {MAX_LINKS} links; remove one with `/context unlink <n>`")
    dst: NodeId = (session.key, to)

    def need(key: str) -> Session:
        if (found := get(key)) is None:
            raise ValueError(f"chat `{key}` was not found")
        return found

    def canon(node: NodeId) -> NodeId:  # a fork's copied prefix is the source chat's own message
        return canonical_node(need, node[0], node[1])

    if canon(source) == canon(dst):
        raise ValueError("a message cannot be linked into itself")
    if any(canon(link.source) == canon(source) and link.target == dst for link in links):
        raise ValueError("that link already exists")
    # A new edge source -> dst closes a cycle exactly when dst is already an ancestor of source.
    graph, _, _ = build_session_graph(owner, lambda k: get(k))
    ancestors, _ = get_ancestor_context(graph, canon(source))
    if canon(dst) in ancestors:
        raise ValueError("that link would create a cycle (the target is already part of the source's history)")

    link = Link(len(links) + 1, source, dst)
    _store(session, [*links, link])
    return link


def remove_link(session: Session, number: int) -> Link:
    links = list_links(session)
    if not 1 <= number <= len(links):
        raise ValueError(f"no link number {number}; `/context links` lists them")
    gone = links[number - 1]
    _store(session, [link for link in links if link.number != number])
    return gone

