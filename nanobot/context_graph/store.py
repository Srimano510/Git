from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from .model import ConversationGraph


class ContextGraphStore:
    """
    JSON persistence for ConversationGraph.

    Persistence failures must not break ordinary chat.
    """

    def __init__(self, root: Path | None = None, *, root_dir: Path | None = None):
        if root is not None and root_dir is not None:
            raise TypeError("provide either root or root_dir, not both")
        self.root = root if root is not None else root_dir
        if self.root is None:
            raise TypeError("root is required")

    def graph_path(
        self,
        workspace_id: str,
        graph_id: str,
    ) -> Path:
        directory = self.root / workspace_id
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        return directory / f"{graph_id}.json"

    def save(
        self,
        graph: ConversationGraph,
        workspace_id: str,
    ) -> Path | None:
        try:
            path = self.graph_path(
                workspace_id,
                graph.graph_id,
            )

            temp_path = path.with_suffix(".tmp")

            temp_path.write_text(
                json.dumps(
                    graph.to_dict(),
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            temp_path.replace(path)

            return path

        except OSError:
            return None

    def load(
        self,
        workspace_id: str,
        graph_id: str,
    ) -> ConversationGraph | None:
        try:
            path = self.graph_path(
                workspace_id,
                graph_id,
            )

            if not path.exists():
                return None

            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            return ConversationGraph.from_dict(data)

        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _legacy_graph_id(session_key: str) -> str:
        return "graph_" + sha256(session_key.encode("utf-8")).hexdigest()

    def save_graph(self, session_key: str, graph: ConversationGraph) -> bool:
        graph.graph_id = self._legacy_graph_id(session_key)
        graph.metadata.setdefault("session_key", session_key)
        return self.save(graph, "legacy_sessions") is not None

    def load_graph(self, session_key: str) -> ConversationGraph:
        graph_id = self._legacy_graph_id(session_key)
        graph = self.load("legacy_sessions", graph_id)
        return graph or ConversationGraph(
            graph_id=graph_id,
            metadata={"session_key": session_key},
        )

    def sync_session_messages(
        self,
        session_key: str,
        messages: list[dict[str, object]],
        graph: ConversationGraph | None = None,
    ) -> ConversationGraph:
        from nanobot.context_graph.sync import synchronize_session

        graph_obj = graph or self.load_graph(session_key)
        synchronize_session(
            graph_obj,
            session_key=session_key,
            messages=messages,
        )
        self.save_graph(session_key, graph_obj)
        return graph_obj