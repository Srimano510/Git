"""Execution transcript models for workflow runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    node_id: str
    node_name: str
    status: str
    input: Any = None
    output: Any = None
    error: str | None = None
    duration_ms: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkflowTranscript:
    run_id: str
    graph_version: str = "v1"
    entries: list[TranscriptEntry] = field(default_factory=list)

    def add(self, entry: TranscriptEntry) -> None:
        self.entries.append(entry)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "graph_version": self.graph_version,
            "entries": [
                entry.to_dict()
                for entry in self.entries
            ],
        }