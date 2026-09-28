"""Observability and result structures for Context Engine executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextResult:
    """Structured context retrieval result returned by context engines."""

    strategy: str
    messages: list[dict[str, Any]]
    node_ids: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    token_count: int = 0
    retrieval_ms: float = 0.0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "messages": self.messages,
            "node_ids": self.node_ids,
            "reasons": self.reasons,
            "token_count": self.token_count,
            "retrieval_ms": self.retrieval_ms,
            "diagnostics": self.diagnostics,
        }
