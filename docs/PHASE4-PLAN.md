# Phase 4 plan: hybrid retrieval (semantic recall) and summaries

Status: **PLAN WRITTEN, owner decisions D1-D8 recorded (section 1). Waiting for the owner to commit the docs; no code written.**
Branch: `phase4`. Spec: [MasterGuide-v3.md](../MasterGuide-v3.md), "Phase 4" (guide text is partly out of date, see section 2).
Governing rule ([AGENTS.md](../AGENTS.md)): minimum code, reuse the existing structure; the typed-edge DAG stays the only new core idea. Semantic recall and summaries are small additions on top of it.

## 1. Decisions (owner answers, 2026-10-18)

| # | Decision | Outcome |
|---|---|---|
| D1 | Embeddings | **Local hashed bag-of-words** (pure Python, deterministic, no dependency or key). Behind one `Embedder` interface so a real model can be swapped in later. Options considered are recorded in [REVIEW-LATER.md](REVIEW-LATER.md). |
| D2 | Index persistence | **Derive each turn, no index file.** Same principle as the Phase 3 DAG. Deviates from the guide's `save/load/reindex` deliverable (recorded in MasterGuide). |
| D3 | Candidate pool | **Both, switchable.** `archived` (own ancestry, messages already dropped by compaction) or `family` (also sibling/descendant branches, via the Phase 3.5 tree builder). Config default `archived`; per-session override. |
| D4 | Injection | **One synthetic "recalled context" message** before the history. Never splices raw messages, so replay legality (tool pairs, turn order) cannot break. |
| D5 | Summaries | **Manual first** (stored in session metadata, created by a command), **LLM generation later** behind a function stub; logged in REVIEW-LATER. |
| D6 | Mode toggle | **Third strategy `hybrid`** in `context_strategy`: `/context hybrid`, and a third item in the existing toggle (header and composer share state since Phase 3.5). |
| D7 | UI flags | **Small version now**: the minimap marks nodes recalled by vector search, summaries, or plain history, enough to verify behaviour. **Phase 6 replaces this with the full Observatory** (noted in the Phase 6 section of the MasterGuide). |
| D8 | Pool switch location | **Config default plus per-session override**: config schema field for the default, `/context hybrid archived|family` stored in session metadata. |

## 2. What changed since the guide was written

The guide assumes the Phase 1-2 design. Phase 3 replaced it, so these guide items are re-specified:

| Guide says | Now |
|---|---|
| `VectorIndex.add/save/load/reindex`, vector file next to the graph JSON | No graph JSON and no index file exist. Embeddings are computed per turn from session messages (D2). Guide test 5 (persistence and re-index) becomes: results are deterministic, nothing is written to disk. |
| `graph.nodes`, `ChatNode.content`, `graph.add_node` | Nodes are addresses `(session_key, index)`; text is read from the session store. |
| SUMMARY node is a `ChatNode` with a SUMMARY edge | A summary is a record in `session.metadata["context_summaries"]`, like `context_edges` (no graph store). |
| Splice semantic hits into the context list | One synthetic recalled-context message (D4). |
| Third mode "Graph + Vector" | Strategy `hybrid` (D6). |

Facts found in the code that shape the design:
- Nothing in nanobot embeds text today, so the embedder is new (small).
- `GraphContextEngine` already drops archived messages (index below `last_archived`) from replay. Semantic recall can bring those back, which linear mode cannot do. This is the clearest demo.
- `GraphContextEngine.build_context` does not receive the user's current message; the loop must pass it as the recall query.
- The existing LLM summarizer (`MemoryStore.summarize_transcript` and the archiver) is async and tied to the provider runtime; reusing it is deferred (D5).
- `nanobot/context_graph/tree.py::build_tree_graph` (Phase 3.5) already finds every session in a chat family; the `family` pool reuses it.

## 3. Design

### 3.1 Embedder (`nanobot/context_graph/embed.py`)
- `Embedder` protocol: `embed(text) -> list[float]`. Default `HashEmbedder`: lowercase word tokens, hashing trick into a fixed dimension using a stable hash (`zlib.crc32`, not Python's salted `hash`), sublinear term weights, L2-normalised; `cosine(a, b)`.
- Deterministic across runs and processes (tests rely on it).

### 3.2 Recall (`nanobot/context_graph/recall.py`, pure)
- Input: query text, candidate messages `[(NodeId, message)]`, embedder, `top_k`, `min_score`.
- Candidates are user/assistant text messages only: skip tool results, hidden/automation history (`is_hidden_history_message`), empty text, and anything already in the replayed history (dedupe).
- Output: ranked hits `[(NodeId, score)]`, each reason `"vector (score 0.42)"`.
- Candidate pools:
  - `archived`: ancestry nodes with index below the owning session's `last_archived`.
  - `family`: nodes of the chat family (via `build_tree_graph`) that are not in the current ancestry. Same visibility filters as above.
- Pool choice: per-session metadata `context_pool` if set, else the config default.

### 3.3 Summaries
- Stored as `session.metadata["context_summaries"] = [{"from": [key, i], "to": [key, j], "text": "..."}]` on the session where the range lives.
- Command `/context summary <from> <to> <text>` (indices into the current session) appends one; `/context summary clear` removes them. Manual only (D5); a `SummaryProvider` hook is left for later LLM generation.
- Rule: nodes in a summary's range that are archived or would be pruned by the token budget are represented by the summary text, with reason `"summary"`. The summary appears in the recalled block, not as a fake message in history.

### 3.4 Engine (`GraphContextEngine`)
- New optional arguments: `query`, `semantic: bool`, `pool`, plus recall settings from config. Existing callers and `strategy="graph"` are unchanged.
- Order of work for `hybrid`: resolve ancestry (Phase 3) -> replay history under the budget minus the recall reservation -> collect candidates -> score -> top_k -> apply summaries -> render one recalled-context message under `recall_token_budget` -> prepend through the same injection point nanobot already uses for compaction summaries (found in P4-0).
- Any embedder or recall failure skips recall for the turn (`diagnostics["semantic_error"]`); the graph history is still returned. A full engine failure keeps the Phase 3 linear fallback.
- Diagnostics (additive): `phase: 4`, `pool`, `semantic_candidates`, `semantic_hits`, `semantic_included`, `embed_ms`, `summaries_used`.

### 3.5 Config (`nanobot/config/schema.py`)
New `ContextGraphConfig` section with defaults and camelCase aliases (old `config.json` files still load): `semantic_pool` (`archived` | `family`, default `archived`), `semantic_top_k` (3), `semantic_min_score` (0.15), `recall_token_budget` (1500). Exact placement on the root config is fixed in P4-0.

### 3.6 Loop and command
- `agent/loop.py`: for `hybrid`, call the engine with `query` = the current user message and the config; save `session.metadata["_last_context"] = {"strategy", "nodes": {node_id: kind}}` (kind: `history` | `vector` | `summary`) after building context.
- `command/builtin.py`: `/context hybrid [archived|family]`, `/context summary ...`; `/context` help text lists `hybrid`.

### 3.7 UI (small version, D7)
- `/api/sessions/{key}/graph` adds an additive field `context: {node_id: kind}` read from `_last_context` (nodes of other sessions are included if recalled from the family).
- Minimap: a small legend and a marker per kind (history ring, vector accent, summary accent) on nodes used in the last turn. No new panel.
- Toggle dropdown (`ContextStrategyBadge`): third item "Hybrid (Graph + Vector)"; `ContextStrategy` type gains `"hybrid"`.
- **Phase 6 replaces this with the full Observatory** (linear vs graph vs hybrid side by side, reasons, token breakdown). See MasterGuide Phase 6 note.

## 4. Tasks (mirrored in [log.md](../log.md)); test-first, each with a done-when

| ID | Task | Done when |
|---|---|---|
| P4-0 | **Audit (read-only):** find where compaction summaries enter the prompt (`ContextBuilder`/`TranscriptInput`), how `/context` parses arguments, root config placement, and every caller of `GraphContextEngine` and `context_strategy` (loop, builtin, webui, session projection) | table of findings in `log.md`; nothing changed |
| P4-1 | `embed.py` + tests | same text -> same vector across processes; related text scores above unrelated; empty text is safe |
| P4-2 | `recall.py` + tests | ranks the planted relevant message first; dedupes against history; skips tool/hidden/empty; honours `top_k` and `min_score`; both pools behave (archived-only excludes siblings, family includes them) |
| P4-3 | Config section + tests | defaults load; camelCase aliases work; an old config without the section loads |
| P4-4 | Summaries store + `/context summary` command + tests | create, list, clear; bad indices rejected; summary replaces archived/pruned range in the recalled block |
| P4-5 | Engine `hybrid` path + tests | recalls an archived message (guide test 2); summary used under a tight budget (test 3); total tokens within budget (test 4); embedder failure degrades to plain graph; `graph` strategy output unchanged |
| P4-6 | Loop integration + `/context hybrid [pool]` + `_last_context` + integration test through `ContextBuilder.build_transcript()` | hybrid turn builds a transcript containing the recalled block; per-session pool override beats the config default |
| P4-7 | `/graph` route `context` field + route test | field present only when a last context exists; existing fields unchanged |
| P4-8 | WebUI: third toggle item, minimap markers, legend + vitest | tests pass; `bun run build` and `bun run lint` clean |
| P4-9 | Browser check with Playwright (AGENTS.md *Browser check*): seed a long chat with an archived relevant message, switch to hybrid, confirm markers and the recalled block | screenshots reviewed; temp gateway stopped |
| P4-10 | Checks: context_graph and touched tests, full `pytest`, `ruff`, `basedpyright`, `bun run test/build/lint` | green apart from the known pre-existing failures |
| P4-11 | Docs: `log.md`, MasterGuide (Phase 4 deviations, Phase 6 note), `docs/REVIEW-LATER.md`, README/config docs for the new config section | updated |

## 5. Risks and honest caveats

- **Hashed bag-of-words is not semantic.** It matches shared words, not meaning ("car" vs "automobile" scores 0). The demo must use text with word overlap, and the write-up must say so. D1 keeps the interface swappable.
- **Graph vs linear still look alike in simple chats** (REVIEW-LATER, Phase 3). Hybrid is the first mode that visibly differs, but only after compaction has archived something or when `family` pool finds sibling content.
- **`family` pool breaks branch isolation by design.** It is opt-in, labelled in the reasons, and off by default.
- **Cost of `family`:** loads every session in the family each turn (same limitation as the Phase 3.5 tree route). Fine for a demo.
- **Injection point** for the recalled message is unknown until P4-0; if no clean point exists, the fallback is the first-user-message prefix in the transcript builder. Will be reported before coding that step.
- **`/context` replies are stored as chat messages** (REVIEW-LATER): `/context summary` and `/context hybrid` will add more of them. Noted, not fixed here.
- The summary text is user-authored; it enters the prompt, so it is treated like any other user content (no special trust).
