# Review later

Decisions the owner should revisit.

- **Graph vs linear look alike in simple chats (Phase 3).** A fork copies the parent prefix and nothing creates CONTEXT edges, so graph mode differs from linear only when a child's copied prefix is trimmed/compacted (graph still reads the source session) or when `session.metadata["context_edges"]` is injected. A small `/context link` command would make the difference visible in the UI.
- **Graph token budget.** `AgentLoop` passes `max_tokens=self.context_window_tokens` to the graph engine (the full window). Linear relies on the compaction pointer instead. Consider a smaller dedicated budget.
- **Orphaned graph files.** Old `<data>/context_graph/**/*.json` files are no longer read or written; safe to delete.
- **Unrelated pre-existing test failures** (fail on the untouched tree too): `tests/agent/test_mcp_reconnect_crash.py`, `tests/session/test_session_location.py::test_equivalent_workspace_paths_share_one_store`, two in `tests/webui/test_session_projection.py`, `test_attach_exposes_the_session_canonical_model_preset` in the websocket channel tests.
- `webui/build-errors.txt` (added by `6ad7c1b5`) kept at the owner's request.
- **Split windows (deferred 2026-10-17).** Show several chats side by side or stacked inside the main chat area, VS Code editor-group style (recursive split layout, e.g. `react-resizable-panels`, one session and composer per pane, drag a minimap node into a pane). Useful for the Linear-vs-Graph same-query demo. Deferred out of Phase 3.5 because every pane needs its own websocket/session state, which is the riskiest part. Revisit after Phase 3.5.
- `ContextObservatory.tsx` calls `/api/sessions/{key}/context-result`, which has no backend route.
