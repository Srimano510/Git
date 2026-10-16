# Phase 3 plan (rev 2): typed-edge DAG context resolution

Status: **IMPLEMENTED (rev 2 approved).** See log.md.
Spec: [MasterGuide-v3.md](../MasterGuide-v3.md), "Phase 3" (line 782) and "Repository-specific implementation notes for Phase 3" (line 918).
Governing rule (top of [AGENTS.md](../AGENTS.md)): minimum code, reuse existing structure, the typed-edge DAG is the only new thing.

## 1. Decisions so far

| # | Decision | Owner answer |
|---|---|---|
| Q1 | Do not copy raw messages into nodes. Messages already persist in the session store, apart from the context builder. | Agreed (see section 2) |
| Q2 | No producer of merge/CONTEXT edges in Phase 3. | Agreed |
| Q3 | Token budget reuses the loop's `max_tokens`; no new config. | Agreed |
| Q4 | Default ancestry stops at the fork, **plus** traversal continues past the fork into the source session's own ancestry (grandparents and beyond). | Agreed, "walk past fork into grandparents" |
| Cut | Derive the DAG from sessions per turn; delete the separate graph store and sync layer. | Agreed |

## 2. Q1 finding: how linear mode persists messages

- Messages live in `Session.messages` and are persisted by `SessionManager` / its store as one JSONL file per session (`nanobot/session/manager.py`: `_save_unlocked`, `_load_unlocked`, atomic writes with fsync). Full dicts are kept, including `tool_calls`, `tool_call_id`, media.
- The context builder never persists anything. `Session.get_history()` is a pure view over `session.messages`: it applies the compaction pointer (`last_archived`), starts at a user turn, drops orphan tool results (`find_legal_message_start`) and honours `max_messages` / `max_tokens`. `ContextBuilder.build_transcript()` then only formats that list.
- `Session.messages` is append-only apart from a full reset; compaction moves the `last_archived` pointer instead of deleting rows, so `(session_key, message_index)` is a stable address.
- A fork copies the parent prefix into the child (`SessionManager.fork_session_before_user_index`) and records `context_graph_source_session_key`, `context_graph_child_session_key` and `context_graph_fork_boundary` in the child's metadata.

Conclusion: the graph needs no message storage and no persistence of its own. A node is just an address `(session_key, index)`, and its message is read from the session store.

## 3. Design

### 3.1 DAG derived per turn, not persisted

- **Node** = `(session_key, index)` into a session's messages. A child's prefix indices below its fork boundary alias the source session's nodes (canonicalised, recursively), so a prefix is one node, not two.
- **REPLY edge** = consecutive messages in one session (implicit).
- **BRANCH edge** = `(source, boundary-1) -> (child, boundary)`, taken from the child's fork metadata that already exists.
- **CONTEXT / REFERENCE edges**: supported by the resolver and the edge model, stored only if present in `session.metadata["context_edges"]` (existing metadata persistence). Nothing writes them in Phase 3 (Q2); tests inject them.
- **Up and above (Q4):** the walk goes tip -> REPLY back to the fork boundary -> BRANCH to the source -> repeat with the source's own fork metadata. Source sessions are loaded with `SessionManager.read_session_snapshot`. This reaches ancestry even when the child's copied prefix was trimmed or compacted.

### 3.2 Resolver (`nanobot/context_graph/resolver.py`, pure)

- `TRAVERSE_EDGE_TYPES = {REPLY, BRANCH, CONTEXT}`; `REFERENCE` opt-in; `SUMMARY` ignored.
- `get_ancestor_context(edges_in, current)`: iterative walk with a visited set (cycle-safe), returns ancestors plus a per-node reason (`current`, `reply`, `branch`, `context`) and counters (`visited`, `returned`).
- Ordering is **topological, parents first, ties by `(session_key, index)`**. Not timestamp: stored messages share near-identical sync times, and the guide's timestamp sort would scramble them.
- Multi-parent merge: a node with several incoming edges pulls in all parents (diamond n1..n4 -> `[n1, n2, n3, n4]`).

### 3.3 Engine

`GraphContextEngine.build_context(session, ..., load_session=None)`:

1. Resolve ordered node addresses from the session tip.
2. Fetch each message from its owning session (current session in memory, others via `load_session`, defaulting to the session manager).
3. **Reuse linear's budgeting and legality instead of rewriting it:** put the resolved messages in a throwaway `Session(messages=...)` and call `get_history(max_messages, max_tokens, extend_to_user)`. That gives token budgeting, orphan-tool-result removal and legal turn starts for free. Pruned count = resolved minus returned.
4. The fresh user input is never added to history (it stays `TranscriptInput.current_message`).
5. Any exception, missing source session, or empty/illegal result: return `session.get_history(...)` for that turn and set `diagnostics["fallback"]`.
6. `ContextResult(strategy="graph", ...)` with `node_ids`, per-node `reasons`, `token_count`, `retrieval_ms`, and diagnostics `visited`, `returned`, `pruned`, `branch_count`, `fallback`.

### 3.4 Linear mode

`LinearContextEngine` is only a wrapper around `session.get_history`. The loop calls `session.get_history` directly for linear and the graph engine for graph; the `ContextResult` shape the loop and UI read stays (additive).

## 4. What gets deleted (non-DAG, duplicates existing infra)

| Remove | Why | Replacement |
|---|---|---|
| `store.py` (`ContextGraphStore`, legacy `save_graph/load_graph/sync_session_messages`, `_default_graph_store`) | second persistence layer for data sessions already hold | derive from sessions |
| `sync.py` (`_sync_session_graph`, `message_to_node`, `synchronize_session`, `record_branch`, `graph_id_for_session`, provenance, graph id metadata) | copies messages into nodes and mirrors session state | address-based nodes; fork metadata keys stay |
| `LinearContextEngine`, `ContextEngineBase` ABC | wrapper over `Session.get_history` | direct call |
| `ChatNode` content/role/timestamp/metadata fields, `ConversationGraph.to_dict/from_dict/to_json`, `provenance_index`, `add_provenance`, `ChatEdge.metadata` | persistence-only | slim node/edge dataclasses |
| Extra `save(source)` and `GRAPH_ID` metadata in `SessionManager.fork_session_before_user_index` | only fed the graph store | keep the three fork metadata keys (move constants out of `sync.py`) |
| Tests: `test_store.py`, `test_linear_engine.py`, serialisation tests in `test_model.py`, graph-store parts of `test_branching.py`, `test_graph_engine.py` | cover removed code | rewritten against the DAG |
| `webui/build-errors.txt` | stray build log from `6ad7c1b5` | none (needs owner OK) |

Audit before deleting: every reference from `nanobot/agent/loop.py`, `nanobot/command/builtin.py`, `nanobot/session/manager.py` and `webui/src` (branch indicator in `ThreadHeader.tsx`) to the removed names or to `branch_count` / graph diagnostics. Anything the UI reads must keep working or be adapted.

## 5. Tasks (mirrored in `log.md`)

All test-first; each has a "done when".

1. **P3-0 Audit.** List references to everything in section 4. *Done when:* a table of callers is in `log.md` and nothing deleted yet.
2. **P3-1 Slim model.** Reduce `model.py` to node address + typed `ChatEdge` + `EdgeType` + incoming-edge index. *Done when:* model tests pass without serialisation.
3. **P3-2 Resolver tests then code.** Diamond, root-only, cycle, branch isolation, CONTEXT edge, topological order. *Done when:* all pass.
4. **P3-3 Derive DAG from sessions.** Build edges from fork metadata, recursive past-the-fork walk, alias canonicalisation. *Done when:* a 3-level fork (grandparent -> parent -> child) with a trimmed child prefix still reaches the grandparent's messages; sibling branch excluded.
5. **P3-4 Engine on `Session.get_history`.** Budget, legality, pruned count, fallback. *Done when:* tight `max_tokens` trims oldest, tool pairs stay legal, resolver failure falls back to linear with `diagnostics["fallback"]`.
6. **P3-5 Remove dead layer.** Delete section-4 items; point the loop at `get_history` for linear; fix `SessionManager` fork code and imports. *Done when:* no references remain and the full `pytest` is green.
7. **P3-6 Integration test.** Two forks feeding a merged context pass through `ContextBuilder.build_transcript()` unchanged. *Done when:* passes.
8. **P3-7 Checks.** `pytest` (context_graph, then full), `ruff check nanobot/`, `basedpyright`, and `bun run test` / `bun run build` if the WebUI changed. *Done when:* green; pre-existing failures noted separately.
9. **P3-8 Docs.** `log.md`, `docs/REVIEW-LATER.md`, README/config docs if user-visible.

## 6. Risks and honest caveats

- **Graph vs linear may look identical in simple chats.** A fork already copies the parent prefix, and Phase 3 adds no merge-edge producer (Q2). The behavioural difference shows only (a) past-the-fork ancestry when the child's copy is trimmed/compacted and (b) injected CONTEXT edges. If the demo needs a visible difference in the UI, a small link command is the cheapest addition; logged for `docs/REVIEW-LATER.md` rather than built.
- Deleting Phase 1-2 persistence rewrites already-merged work and several tests; the audit task (P3-0) guards against breaking the WebUI indicator and `SessionManager`.
- Old `~/.nanobot/.../context_graph/*.json` files become orphaned; they are ignored, not migrated (derived data, safe to delete). This is the one "stored data" removal, so it needs your explicit OK.
- Source session deleted or renamed: handled by the per-turn linear fallback.
