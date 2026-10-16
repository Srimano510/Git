# Review later

Decisions the owner should revisit.

- **Graph vs linear look alike in simple chats (Phase 3).** A fork copies the parent prefix and nothing creates CONTEXT edges, so graph mode differs from linear only when a child's copied prefix is trimmed/compacted (graph still reads the source session) or when `session.metadata["context_edges"]` is injected. A small `/context link` command would make the difference visible in the UI.
- **Graph token budget.** `AgentLoop` passes `max_tokens=self.context_window_tokens` to the graph engine (the full window). Linear relies on the compaction pointer instead. Consider a smaller dedicated budget.
- **Orphaned graph files.** Old `<data>/context_graph/**/*.json` files are no longer read or written; safe to delete.
- **Unrelated pre-existing test failures** (fail on the untouched tree too): `tests/agent/test_mcp_reconnect_crash.py`, `tests/session/test_session_location.py::test_equivalent_workspace_paths_share_one_store`, two in `tests/webui/test_session_projection.py`, `test_attach_exposes_the_session_canonical_model_preset` in the websocket channel tests.
- `webui/build-errors.txt` (added by `6ad7c1b5`) kept at the owner's request.
- `ContextObservatory.tsx` calls `/api/sessions/{key}/context-result`, which has no backend route.
