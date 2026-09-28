"""Storage and persistence layer for Conversation Graphs."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.config.paths import get_runtime_subdir
from nanobot.context_graph.model import ChatEdge, ChatNode, ConversationGraph, EdgeType
from nanobot.utils.helpers import ensure_dir


class ContextGraphStore:
    """Manages file persistence and message-synchronization for conversation graphs."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = (
            Path(root_dir).expanduser().resolve(strict=False)
            if root_dir is not None
            else get_runtime_subdir("context-graphs").resolve(strict=False)
        )
        ensure_dir(self.root_dir)

    @staticmethod
    def storage_key(session_key: str) -> str:
        """Derive a filesystem-safe filename stem for a given session key."""
        return base64.urlsafe_b64encode(session_key.encode()).decode().rstrip("=")

    def get_graph_path(self, session_key: str) -> Path:
        """Return the target JSON file path for a session's conversation graph."""
        return self.root_dir / f"{self.storage_key(session_key)}.json"

    def load_graph(self, session_key: str) -> ConversationGraph:
        """Load a conversation graph from disk, or return a new empty graph if none exists."""
        path = self.get_graph_path(session_key)
        if not path.exists():
            return ConversationGraph(metadata={"session_key": session_key})

        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
                return ConversationGraph.from_json(content)
        except Exception as exc:
            logger.warning("Failed to load context graph for session {}: {}", session_key, exc)
            return ConversationGraph(metadata={"session_key": session_key})

    def save_graph(self, session_key: str, graph: ConversationGraph) -> bool:
        """Persist a conversation graph to disk atomically."""
        path = self.get_graph_path(session_key)
        tmp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            ensure_dir(self.root_dir)
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(graph.to_json())
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            return True
        except Exception as exc:
            logger.warning("Failed to save context graph for session {}: {}", session_key, exc)
            return False
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _derive_node_id(session_key: str, index: int, message: dict[str, Any]) -> str:
        """Generate a deterministic node ID for a session message."""
        turn_id = message.get("turn_id")
        msg_id = message.get("id") or message.get("message_id")
        if msg_id:
            return f"node_{msg_id}"
        if turn_id:
            role = message.get("role", "msg")
            return f"node_{turn_id}_{role}_{index}"
        content = str(message.get("content", ""))
        digest = hashlib.sha256(f"{session_key}:{index}:{content}".encode()).hexdigest()[:12]
        return f"node_{digest}"

    def sync_session_messages(
        self,
        session_key: str,
        messages: list[dict[str, Any]],
        graph: ConversationGraph | None = None,
    ) -> ConversationGraph:
        """
        Synchronize a list of session replay messages into the graph idempotently.
        Preserves existing nodes/edges and appends missing messages.
        """
        if graph is None:
            graph = self.load_graph(session_key)

        prev_node_id: str | None = None
        # Find the last node if graph already has nodes
        if graph.nodes:
            # Look for existing node with the highest message index
            indexed_nodes = [
                node for node in graph.nodes.values()
                if node.session_key == session_key and node.session_message_index is not None
            ]
            if indexed_nodes:
                indexed_nodes.sort(key=lambda n: n.session_message_index or 0)
                prev_node_id = indexed_nodes[-1].id

        for idx, msg in enumerate(messages):
            node_id = self._derive_node_id(session_key, idx, msg)
            if node_id not in graph.nodes:
                role = str(msg.get("role", "user"))
                content = str(msg.get("content", ""))
                turn_id = msg.get("turn_id")
                timestamp = msg.get("timestamp") or msg.get("created_at")
                ts = float(timestamp) if isinstance(timestamp, (int, float)) else None

                node = ChatNode(
                    id=node_id,
                    role=role,
                    content=content,
                    timestamp=ts or (0.0 if ts is not None else float(idx)),
                    session_key=session_key,
                    session_message_index=idx,
                    turn_id=str(turn_id) if turn_id else None,
                    metadata={
                        k: v for k, v in msg.items()
                        if k not in {"role", "content", "turn_id", "timestamp"}
                    },
                )
                graph.add_node(node)

                if prev_node_id and prev_node_id != node_id:
                    # Check if edge already exists
                    edge_exists = any(
                        edge.source == prev_node_id and edge.target == node_id
                        for edge in graph.edges
                    )
                    if not edge_exists:
                        edge_type = EdgeType.REPLY.value
                        graph.add_edge(ChatEdge(source=prev_node_id, target=node_id, type=edge_type))

            prev_node_id = node_id

        return graph


_default_store: ContextGraphStore | None = None


def get_context_graph_store() -> ContextGraphStore:
    """Get the default process-wide context graph store."""
    global _default_store
    if _default_store is None:
        _default_store = ContextGraphStore()
    return _default_store
