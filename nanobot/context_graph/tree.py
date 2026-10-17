"""Whole-family chat tree for the WebUI minimap, plus node -> fork mapping."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from nanobot.session import Session
from nanobot.session.history_visibility import is_hidden_history_message

from .derive import FORK_CHILD_KEY, FORK_SOURCE_KEY, build_session_graph
from .model import ChatEdge, ConversationGraph, NodeId

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


def message_text(message: Mapping[str, Any]) -> str:
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
    text = " ".join(message_text(message).split())
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + "…"


def _node_id(node: NodeId) -> str:
    return f"{node[0]}#{node[1]}"


@dataclass
class Family:
    """The chat family of one session: canonical nodes (aliased fork prefixes merged)."""

    root: str
    graph: ConversationGraph
    nodes: set[NodeId]
    tips: dict[str, str]
    sessions: dict[str, Session]


def load_family(
    key: str,
    session_rows: Sequence[Mapping[str, Any]],
    load_session: Callable[[str], Session | None],
) -> Family | None:
    """Return the family containing ``key``: the root fork source plus every session
    forked from it, recursively. ``None`` when ``key`` is unknown."""
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
    return Family(root, graph, nodes, tips, sessions)


def _without_commands(
    graph: ConversationGraph,
    nodes: set[NodeId],
    tips: dict[str, str],
    sessions: Mapping[str, Session],
) -> tuple[list[ChatEdge], set[NodeId], dict[str, str]]:
    """Drop slash-command turns (``_command``) from the view, bridging the chain around them.

    The nodes stay in the DAG (indices are addresses); they are just not shown.
    """

    def hidden(n: NodeId) -> bool:
        owner = sessions.get(n[0])
        return owner is not None and n[1] < len(owner.messages) and bool(
            owner.messages[n[1]].get("_command")
        )

    skip = {n for n in nodes if hidden(n)}
    edges = list(graph.edges)
    for h in sorted(skip):
        ins = [e for e in edges if e.target == h]
        outs = [e for e in edges if e.source == h]
        edges = [e for e in edges if e not in ins and e not in outs]
        edges += [ChatEdge(i.source, o.target, o.type) for i in ins for o in outs]

    def visible_tip(tip: str) -> str:
        key, _, idx = tip.rpartition("#")
        node = (key, int(idx))
        while node in skip and (parents := graph.incoming(node)):
            node = parents[0].source
        return _node_id(node)

    return edges, nodes - skip, {k: visible_tip(t) for k, t in tips.items()}


def build_tree_graph(
    key: str,
    session_rows: Sequence[Mapping[str, Any]],
    load_session: Callable[[str], Session | None],
) -> dict[str, Any] | None:
    """Return nodes, typed edges and per-chat tips for the family containing ``key``."""
    family = load_family(key, session_rows, load_session)
    if family is None:
        return None
    root, graph, nodes, tips, sessions = (
        family.root, family.graph, family.nodes, family.tips, family.sessions,
    )
    edges, nodes, tips = _without_commands(graph, nodes, tips, sessions)
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
            node["text"] = message_text(m)  # lets the UI prefill a re-ask
        out_nodes.append(node)
    out_edges = sorted(
        (
            {"source": _node_id(e.source), "target": _node_id(e.target), "type": e.type.value}
            for e in edges
        ),
        key=lambda e: (e["source"], e["target"], e["type"]),
    )
    result: dict[str, Any] = {"root": root, "nodes": out_nodes, "edges": out_edges, "tips": tips}
    last = cast(object, sessions[key].metadata.get("_last_context"))  # last graph/hybrid turn
    if isinstance(last, dict):
        last_ctx = cast(dict[str, Any], last)
        if isinstance(last_ctx.get("nodes"), dict):
            result["context"] = last_ctx["nodes"]
            result["context_strategy"] = last_ctx.get("strategy")
    return result
