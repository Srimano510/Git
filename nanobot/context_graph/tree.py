"""Whole-family chat tree for the WebUI minimap, plus node -> fork mapping."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from nanobot.session import Session
from nanobot.session.history_visibility import is_hidden_history_message

from .derive import FORK_CHILD_KEY, FORK_SOURCE_KEY, build_session_graph
from .model import ConversationGraph, NodeId

PREVIEW_CHARS = 80


def node_to_fork_args(messages: Sequence[Mapping[str, Any]], index: int) -> tuple[int, bool]:
    """Map a message index to ``fork_session_before_user_index`` arguments.

    A visible user node means "re-ask": the fork stops before it. Any other node keeps its
    turn: the fork stops before the next user message, so it includes the whole turn.
    """
    if not 0 <= index < len(messages):
        raise ValueError(f"message index {index} out of range")

    def visible_user(m: Mapping[str, Any]) -> bool:
        return m.get("role") == "user" and not is_hidden_history_message(m)

    users_before = sum(1 for m in messages[:index] if visible_user(m))
    return users_before, False


def _text(message: Mapping[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, list):
        blocks = cast(list[Any], content)
        return " ".join(
            str(cast(dict[str, Any], b).get("text", ""))
            for b in blocks
            if isinstance(b, dict) and cast(dict[str, Any], b).get("type") == "text"
        )
    return str(content or "")


def _preview(message: Mapping[str, Any]) -> str:
    text = " ".join(_text(message).split())
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + "…"


def _node_id(node: NodeId) -> str:
    return f"{node[0]}#{node[1]}"


def build_tree_graph(
    key: str,
    session_rows: Sequence[Mapping[str, Any]],
    load_session: Callable[[str], Session | None],
) -> dict[str, Any] | None:
    """Return nodes, typed edges and per-chat tips for the family containing ``key``.

    The family is the root fork source plus every session forked from it, recursively.
    Returns ``None`` when ``key`` is unknown.
    """
    sessions: dict[str, Session] = {}
    for row in session_rows:
        k = row.get("key")
        if isinstance(k, str) and (s := load_session(k)) is not None:
            sessions[k] = s
    if key not in sessions:
        return None

    def source_of(s: Session) -> str | None:
        src = s.metadata.get(FORK_SOURCE_KEY)
        return src if s.metadata.get(FORK_CHILD_KEY) == s.key and isinstance(src, str) else None

    root, seen = key, {key}
    while (src := source_of(sessions[root])) and src in sessions and src not in seen:
        root = src
        seen.add(src)

    children: dict[str, list[str]] = {}
    for k, s in sessions.items():
        if (src := source_of(s)) is not None:
            children.setdefault(src, []).append(k)
    family: list[str] = []
    stack = [root]
    while stack:
        k = stack.pop()
        family.append(k)
        stack.extend(children.get(k, []))

    graph = ConversationGraph()
    tips: dict[str, str] = {}
    nodes: set[NodeId] = set()
    for k in family:
        try:
            g, tip, _ = build_session_graph(sessions[k], sessions.get)
        except LookupError:  # fork source is gone: show this chat as its own chain
            g, tip, _ = build_session_graph(Session(key=k, messages=sessions[k].messages), sessions.get)
        for e in g.edges:
            graph.add_edge(e.source, e.target, e.type)
        if tip is not None:
            nodes.add(tip)
            tips[k] = _node_id(tip)
    for e in graph.edges:
        nodes.update((e.source, e.target))

    out_nodes: list[dict[str, Any]] = []
    for k, i in sorted(nodes):
        owner = sessions.get(k)
        if owner is None or i >= len(owner.messages):
            continue
        m = owner.messages[i]
        node: dict[str, Any] = {
            "id": _node_id((k, i)),
            "session_key": k,
            "index": i,
            "role": m.get("role"),
            "preview": _preview(m),
            "fork_before_user_index": node_to_fork_args(owner.messages, i)[0],
        }
        if m.get("role") == "user":
            node["text"] = _text(m)  # lets the UI prefill a re-ask
        out_nodes.append(node)
    out_edges = sorted(
        (
            {"source": _node_id(e.source), "target": _node_id(e.target), "type": e.type.value}
            for e in graph.edges
        ),
        key=lambda e: (e["source"], e["target"], e["type"]),
    )
    return {"root": root, "nodes": out_nodes, "edges": out_edges, "tips": tips}
