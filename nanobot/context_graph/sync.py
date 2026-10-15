from __future__ import annotations

from hashlib import sha256
import time
from typing import Any

from loguru import logger

from .model import (
    ChatNode,
    ConversationGraph,
    EdgeType,
)
from .store import ContextGraphStore

GRAPH_ID_METADATA_KEY = "context_graph_id"
FORK_SOURCE_SESSION_METADATA_KEY = "context_graph_source_session_key"
FORK_CHILD_SESSION_METADATA_KEY = "context_graph_child_session_key"
FORK_BOUNDARY_METADATA_KEY = "context_graph_fork_boundary"


def graph_id_for_session(session_key: str) -> str:
    return "graph_" + sha256(session_key.encode("utf-8")).hexdigest()


def _sync_session_graph(
    session: Any,
    store: ContextGraphStore,
    graph: ConversationGraph | None = None,
) -> tuple[ConversationGraph, list[str], float, int]:
    started = time.perf_counter()
    graph_id = graph.graph_id if graph is not None else session.metadata.get(GRAPH_ID_METADATA_KEY)
    if not isinstance(graph_id, str) or not graph_id:
        graph_id = graph_id_for_session(session.key)
    session.metadata[GRAPH_ID_METADATA_KEY] = graph_id

    graph_obj = graph or store.load("sessions", graph_id)
    if graph_obj is None:
        graph_obj = ConversationGraph(graph_id=graph_id)
    branch_count_before = graph_obj.branch_count()

    source_session = session.metadata.get(FORK_SOURCE_SESSION_METADATA_KEY)
    child_session = session.metadata.get(FORK_CHILD_SESSION_METADATA_KEY)
    fork_boundary = session.metadata.get(FORK_BOUNDARY_METADATA_KEY)
    if child_session != session.key:
        source_session = None
        fork_boundary = None
    if not isinstance(source_session, str):
        source_session = None
    if not isinstance(fork_boundary, int) or isinstance(fork_boundary, bool):
        fork_boundary = None

    nodes = synchronize_session(
        graph_obj,
        session_key=session.key,
        messages=session.messages,
        source_session=source_session,
        fork_boundary=fork_boundary,
    )
    saved_path = store.save(graph_obj, "sessions")
    elapsed_ms = (time.perf_counter() - started) * 1000
    branches_added = graph_obj.branch_count() - branch_count_before
    if saved_path is None:
        logger.warning("Context graph persistence failed for graph {}", graph_obj.graph_id)
    if branches_added:
        logger.info(
            "Added {} context-graph branch edge(s); total={}, sync_ms={:.2f}",
            branches_added,
            graph_obj.branch_count(),
            elapsed_ms,
        )
    return graph_obj, [node.id for node in nodes], elapsed_ms, branches_added


def message_to_node(
    message: dict[str, Any],
    *,
    session_key: str,
    message_index: int,
) -> ChatNode:
    """
    Convert an existing nanobot session message into
    a graph node.
    """

    role = str(message.get("role", "unknown"))

    content = message.get("content", "")

    if isinstance(content, list):
        # Preserve textual content without attempting to
        # redesign nanobot's attachment/tool representation.
        text_parts = []

        for item in content:
            if isinstance(item, dict):
                text = item.get("text")

                if isinstance(text, str):
                    text_parts.append(text)

        content = "\n".join(text_parts)

    if not isinstance(content, str):
        content = str(content)

    return ChatNode.create(
        role=role,
        content=content,
        session_key=session_key,
        session_message_index=message_index,
        turn_id=message.get("turn_id"),
        message_id=message.get("id"),
    )


def synchronize_session(
    graph: ConversationGraph,
    *,
    session_key: str,
    messages: list[dict[str, Any]],
    source_session: str | None = None,
    fork_boundary: int | None = None,
) -> list[ChatNode]:
    """
    Idempotently synchronize a session's messages.

    Existing nodes are reused.

    Consecutive messages in the same session receive
    REPLY edges.
    """

    nodes: list[ChatNode] = []
    branch_boundary = (
        fork_boundary
        if source_session is not None
        and source_session != session_key
        and isinstance(fork_boundary, int)
        and not isinstance(fork_boundary, bool)
        and fork_boundary >= 0
        else None
    )

    for index, message in enumerate(messages):
        if branch_boundary is not None and index < branch_boundary:
            source_node_id = graph.provenance_index.get((source_session, index))
            if source_node_id is None:
                source_node = graph.add_node(
                    message_to_node(
                        message,
                        session_key=source_session,
                        message_index=index,
                    )
                )
                source_node_id = source_node.id
            node = graph.nodes[source_node_id]
            graph.add_provenance(session_key, index, source_node_id)
        else:
            node = graph.add_node(
                message_to_node(
                    message,
                    session_key=session_key,
                    message_index=index,
                )
            )

        nodes.append(node)

    for index, (previous, current) in enumerate(zip(nodes, nodes[1:]), start=1):
        if branch_boundary is not None and index == branch_boundary:
            continue
        graph.add_edge(
            previous.id,
            current.id,
            EdgeType.REPLY,
        )

    if branch_boundary is not None and 0 < branch_boundary < len(nodes):
        record_branch(
            graph,
            source_session=source_session,
            child_session=session_key,
            fork_boundary=branch_boundary,
            child_message_index=branch_boundary,
        )

    return nodes


def record_branch(
    graph: ConversationGraph,
    *,
    source_session: str,
    child_session: str,
    fork_boundary: int,
    child_message_index: int,
) -> bool:
    """
    Record the first divergent message of a forked session.

    Returns False until the required nodes exist.
    """

    source_key = (
        source_session,
        fork_boundary - 1,
    )

    child_key = (
        child_session,
        child_message_index,
    )

    source_node_id = graph.provenance_index.get(source_key)
    child_node_id = graph.provenance_index.get(child_key)

    if source_node_id is None:
        return False

    if child_node_id is None:
        return False

    graph.add_branch(
        source_node_id,
        child_node_id,
        source_session=source_session,
        child_session=child_session,
        fork_boundary=fork_boundary,
    )

    return True