# REVIEW-GUIDE.md: where the implementation lives

Cheat sheet for the project review. It lists everything changed or added relative to stock **nanobot**, with file, line and what to say.

- **Baseline used for "original nanobot"**: commit `f98784a3` (the last commit before any context-graph work; nanobot was imported unmodified before it). Regenerate any diff with `git diff f98784a3 HEAD -- <path>`.
- **Size of the change**: 81 files, about +8,400 / -60 lines. About 1,700 lines are the new `nanobot/context_graph/` package. The rest is small hooks into existing files, tests (about 4,400 lines), demo scripts and WebUI.
- Line numbers are from the current `master`. If a file was edited since, search for the function name instead.

---

## 0. The 30-second story (say this first)

> Stock nanobot builds the model's context by replaying one chat's messages, newest first, until the token budget is full (`Session.get_history`). We changed **how context is chosen**. Every message becomes a node in a **typed-edge DAG** (REPLY, BRANCH, CONTEXT). To build a turn's context we walk **all ancestors** of the current message through those edges, so forked chats and manually linked messages contribute. On top of that we added **relevance pruning** (keep what matters under a budget) and **hybrid** mode (semantic recall + summaries). Everything else (loop, runner, providers, channels, session storage) is reused.

The three strategies, switchable per chat with `/context linear|graph|hybrid`:

| Strategy | What it does | Where |
|---|---|---|
| `linear` | Stock nanobot behaviour, untouched (`session.get_history`) | `nanobot/session/manager.py:330` (original) |
| `graph` | Walk typed-edge ancestors, replay them, optionally prune by relevance | `engines.py`, `resolver.py`, `derive.py` |
| `hybrid` | `graph` + a "[Recalled Context]" block of similar old messages and summaries | `engines.py::_recall`, `recall.py`, `summaries.py` |

---

## 1. One turn, end to end (the path to trace in a live demo)

1. User sends a message. `AgentLoop` handles the turn: [nanobot/agent/loop.py:1992](nanobot/agent/loop.py#L1992) now calls `self._turn_history(...)` instead of `session.get_history(...)`. **This is the single switch point.**
2. `_turn_history` ([loop.py:765](nanobot/agent/loop.py#L765)) reads `session.metadata["context_strategy"]`.
   - `linear` calls the original `session.get_history`.
   - `graph` or `hybrid` calls `_graph_context` ([loop.py:740](nanobot/agent/loop.py#L740)), which runs `GraphContextEngine.build_context(...)`.
3. `build_context` ([engines.py:52](nanobot/context_graph/engines.py#L52)):
   1. `build_session_graph` ([derive.py:47](nanobot/context_graph/derive.py#L47)) derives the DAG from the saved sessions.
   2. `get_ancestor_context` ([resolver.py:13](nanobot/context_graph/resolver.py#L13)) returns every ancestor of the tip in topological order, with a reason for each.
   3. Optional relevance pruning ([prune.py](nanobot/context_graph/prune.py)) when `graph_token_budget > 0`.
   4. The kept nodes are replayed through the original `Session.get_history`, which handles legality (tool calls stay with results) and budget.
   5. Hybrid only: `_recall` ([engines.py:166](nanobot/context_graph/engines.py#L166)) adds summaries and similarity hits as one text block.
4. The result (`ContextResult`, [observability.py](nanobot/context_graph/observability.py)) goes back to the loop. The loop passes `result.recalled` into `TranscriptInput.recalled_context` ([loop.py:822](nanobot/agent/loop.py#L822)). `ContextBuilder` appends it to the system prompt as `[Recalled Context]` ([agent/context.py:157](nanobot/agent/context.py#L157)).
5. The loop records per-turn diagnostics in the session metadata (`_last_context`, `_last_workflow`, `_last_turn`). The WebUI reads them through two read-only routes to draw the minimap, the workflow and the Observatory.

**Safety property to mention**: the graph engine never raises into the turn. Any failure falls back to the linear history (`engines.py:140-143`), and pruning, recall and the comparison recorder each catch their own errors.

---

## 2. Backend: new package `nanobot/context_graph/`

### 2.1 Core: the typed-edge DAG (**the one new idea; start here**)

| File | What it holds | Key points |
|---|---|---|
| [model.py](nanobot/context_graph/model.py) | `NodeId = (session_key, message_index)`; `EdgeType` enum (L15); `ChatEdge` (L26); `ConversationGraph` with `add_edge` / `incoming` (L32-46) | A node is an **address** into the session store, so no message text is duplicated. Edge types: `REPLY`, `BRANCH`, `CONTEXT` are followed for context. `REFERENCE`, `SUMMARY` are defined but unused. `TRIGGERS`, `FEEDS` are workflow-only. |
| [derive.py](nanobot/context_graph/derive.py) | `build_session_graph` (L47-87) builds the DAG from already-saved sessions. `fork_of` (L26), `canonical_node` (L41) | **REPLY** = message *i-1* to *i*. **BRANCH** = from a fork's parent message to the first new message of the child (from fork metadata). **CONTEXT** = manual links stored in `session.metadata["context_edges"]`. A fork's copied prefix is an alias of the source chat's nodes, so ancestry continues through the source and nothing is counted twice. |
| [resolver.py](nanobot/context_graph/resolver.py) | `get_ancestor_context` (L13-59), a pure function with no I/O | Reverse DFS from the current node through only `REPLY/BRANCH/CONTEXT` edges (`TRAVERSE_EDGE_TYPES`, L10). It orders the result with **Kahn's algorithm** (a topological sort) and a heap, breaking ties by `(session_key, index)`. It tolerates cycles and records why each node was included (`reason`). |
| [engines.py](nanobot/context_graph/engines.py) | `GraphContextEngine.build_context` (L52-164) | Orchestrates everything in section 1, step 3. Skips `_command` messages and archived indices. Budget logic is at L70-76. |
| [observability.py](nanobot/context_graph/observability.py) | `ContextResult` dataclass (messages, node_ids, reasons, token_count, retrieval_ms, diagnostics, `recalled`) | The return type of the engine. `kinds()` labels each node `history`, `vector` or `summary`. |

**Likely questions**
- *"How is it a DAG and not just a list?"* A forked chat has a BRANCH edge to its parent chat, and a linked message adds a CONTEXT edge, so a node can have several parents. Linear replay can't express that.
- *"Why no stored graph?"* The graph is **derived per turn** from sessions nanobot already persists (fork metadata plus `context_edges`). There is no second source of truth to keep in sync. Phase 3 deleted an earlier store/sync layer for this reason.
- *"What stops a cycle?"* `get_ancestor_context` marks nodes as seen when it first reaches them, so it terminates. `links.add_link` also refuses links that would create a cycle.

### 2.2 Hybrid retrieval and pruning (Phases 4, 7)

| File | What it holds | Key points |
|---|---|---|
| [embed.py](nanobot/context_graph/embed.py) | `HashEmbedder` (L38): sparse hashed bag-of-words, no dependency. `cosine` (L58). `Model2VecEmbedder` (L75): optional local dense model (`minishlab/potion-base-8M`). `make_embedder` (L142): picks one per config and **falls back to hash on any failure**. `main` (L165): `python -m nanobot.context_graph.embed` prefetches the model | A free chat model (OpenCode Zen) has no embeddings endpoint, so embeddings are **local**. Each embedder has its own `default_min_score` (hash 0.15, model2vec 0.30). |
| [recall.py](nanobot/context_graph/recall.py) | `recall` (L26): top-k user/assistant messages above a min score. `pool_candidates` (L54): which messages may come back | Pools: `archived` (this chat's ancestry that was dropped) or `family` (every branch of the chat family). |
| [prune.py](nanobot/context_graph/prune.py) | `split_turns` (L30), `prune_by_relevance` (L48) | **The "selective" part.** If ancestry exceeds `graph_token_budget`, always keep the last `keep_recent_turns` turns; older turns compete for the remaining budget by cosine similarity to the current message. Turns are kept whole so tool calls stay with their results. Turns already covered by a summary are dropped before ranking. |
| [summaries.py](nanobot/context_graph/summaries.py) | `add_summary` (L57), `usable_summaries` (L75), `all_summaries` (L82) | A summary of messages *a-b* is stored in session metadata (`context_summaries`). It is used **only if every node it covers was dropped from replay**, so nothing is shown twice. Ranges resolve to canonical nodes, so they work across forks. |
| [summarize.py](nanobot/context_graph/summarize.py) | `generate_summary` (L47+), `transcript_for` (L33) | `/context summarize a b`: one tool-free LLM call. The transcript is treated as data (the system prompt says to ignore instructions inside it). Failure stores nothing. |
| [links.py](nanobot/context_graph/links.py) | `add_link` (L66), `list_links` (L45), `remove_link` (L119), `parse_node` (L29); `MAX_LINKS = 20` | Manual CONTEXT edges: "message *n* of chat X feeds message *m* of this chat". Validates that both ends exist and that there is no cycle. |

### 2.3 Visualisation, diagnostics and demo support

| File | What it does |
|---|---|
| [tree.py](nanobot/context_graph/tree.py) | `build_tree_graph` (L192): the JSON for the minimap (nodes, typed edges, tips, last-turn context, workflow). `node_to_fork_args` (L18) maps a clicked node to fork arguments. `load_family` (L66) finds all chats related by forking. `turn_anchor` (L154) |
| [workflow.py](nanobot/context_graph/workflow.py) | `build_workflow` (L19): a small DAG of the turn's stages (ContextStrategySelection, GraphTraversal, SemanticSearch, ContextMerge, PromptBuild, LLMCall) using `TRIGGERS`/`FEEDS` edges. It is **display only**: those edge types are never followed by the context resolver, so it can't affect the prompt. |
| [observatory.py](nanobot/context_graph/observatory.py) | `compare` (L97): builds all three strategies for the same query and compares nodes, tokens and timing. `build_observatory` (L203): serves the recording stored at turn time, or rebuilds it. `MAX_NODES = 120` |
| [__init__.py](nanobot/context_graph/__init__.py) | Re-exports |

---

## 3. Edits inside original nanobot files (the "what did you touch" list)

These are the **only** places existing nanobot code changed. Each is small and additive.

| File | Lines | Change |
|---|---|---|
| [nanobot/agent/loop.py](nanobot/agent/loop.py) | L56-60, L146, L278, L360, L521 | Imports; `TurnContext.context_result`; new `context_graph_config` constructor parameter; wired in `from_config` |
| | **L740-800** `_graph_context` | Builds graph/hybrid context and writes `_last_context` and `_last_workflow` to session metadata |
| | **L765-800** `_turn_history` | Strategy switch; records `_last_turn`; logs `Context strategy=... nodes=... tokens=... ms=...` |
| | L802-815 `_record_comparison` | Optional diagnostic: builds the other two strategies and stores the comparison. Wrapped in try/except; never affects the turn |
| | L822 | Passes `recalled` into `TranscriptInput` |
| | **L1992** | **The one-line switch**: `session.get_history(...)` becomes `self._turn_history(...)` |
| [nanobot/agent/context.py](nanobot/agent/context.py) | L84, L113, L157-158, L303 | New optional `recalled_context`; appended to the system prompt as `[Recalled Context]`, placed last so the cacheable prefix stays stable |
| [nanobot/session/manager.py](nanobot/session/manager.py) | L70-77, L1888+ | Volatile-metadata keys (so forks don't inherit `_last_*`). `fork_session_before_user_index` gets `include_user_message` and **writes fork provenance** (`context_graph_source_session_key`, `..._child_session_key`, `..._fork_boundary`), which is what creates BRANCH edges |
| [nanobot/command/builtin.py](nanobot/command/builtin.py) | L100-108 (spec), **L428-503** `cmd_context`, L505 `_context_summarize`, L538 `_context_links`, L1217 (router) | The `/context` slash command: `linear/graph/hybrid [pool]`, `summary`, `summarize`, `link`, `links`, `unlink` |
| [nanobot/config/schema.py](nanobot/config/schema.py) | **L53-77** `ContextGraphConfig`, L469 `Config.context_graph`, L419-430 and L484 lazy-resolve guards | New config section `contextGraph` (camelCase alias; defaults, so old configs still load). The `__init__`/`model_validate` guards fix an import-order bug found along the way |
| [nanobot/webui/ws_http.py](nanobot/webui/ws_http.py) | L703-712 (routes), **L765** `_handle_session_graph_get`, **L787** `_handle_session_context_result_get` | Two new **read-only** routes: `GET /api/sessions/{key}/graph` and `/context-result`. Both check the API token and WebSocket-session keys |
| [nanobot/webui/forking.py](nanobot/webui/forking.py), [transcript.py](nanobot/webui/transcript.py) | small | `include_user_message` flag: fork **including** the clicked user message (to re-ask from an earlier node) |
| [nanobot/webui/session_list_index.py](nanobot/webui/session_list_index.py), [session_projection.py](nanobot/webui/session_projection.py) | few lines | Expose `context_strategy` per chat; index version 8 to 9 |
| [pyproject.toml](pyproject.toml) | L26, L108 | New optional extra `semantic = ["model2vec>=0.10.0"]`. **Also moved `pytest` from the dev group into main dependencies. Probably unintended: be ready to explain or revert** |

---

## 4. Frontend (`webui/src/`)

| File | What it does | Notes |
|---|---|---|
| [components/thread/ContextStrategyBadge.tsx](webui/src/components/thread/ContextStrategyBadge.tsx) | Linear / Graph / Hybrid toggle | Shown in the composer ([ThreadComposer.tsx:2465](webui/src/components/thread/ThreadComposer.tsx#L2465)). It sends `/context <strategy>` over the chat transport, so the toggle and the slash command share one code path |
| [components/thread/ChatMinimap.tsx](webui/src/components/thread/ChatMinimap.tsx) (445 lines) | Chat-tree panel on React Flow + dagre | Click a node to open the chat there. Send from an earlier node = fork then send. Link mode draws CONTEXT edges dotted blue. Amber = vector hit, teal = summary. Workflow toggle |
| [lib/chat-tree.ts](webui/src/lib/chat-tree.ts) | Pure layout helpers: `collapseRuns` (L65), `layoutTree` (L144), `ancestorIds` (L160), `withWorkflow` (L130) | Collapses long REPLY runs so big chats stay readable |
| [components/thread/ContextObservatory.tsx](webui/src/components/thread/ContextObservatory.tsx) | Drawer comparing linear vs graph vs hybrid for the last turn | Shows nodes sent, tokens, time and why each node was kept. Labels data **recorded** vs **rebuilt** |
| [lib/api.ts](webui/src/lib/api.ts) | `fetchSessionGraph` (L308), `fetchContextResult` (L358) | Call the two new routes |
| [lib/nanobot-client.ts](webui/src/lib/nanobot-client.ts) | `forkChat` (L930) | Sends `include_user_message` |
| [components/thread/ThreadShell.tsx](webui/src/components/thread/ThreadShell.tsx) | L1799 (Observatory), L1914 (Minimap) | Mounts both panels (+178 lines) |
| [components/MessageBubble.tsx](webui/src/components/MessageBubble.tsx), [ThreadMessages.tsx](webui/src/components/thread/ThreadMessages.tsx), [App.tsx](webui/src/App.tsx), [lib/types.ts](webui/src/lib/types.ts), [hooks/useSessions.ts](webui/src/hooks/useSessions.ts) | small | Fork-from-message control, strategy type, wiring |
| i18n (10 locales) | new `thread.observatory.*`, minimap and link keys | |

---

## 5. Demo kit (`scripts/`)

| File | Purpose |
|---|---|
| [scripts/seed_demo.py](scripts/seed_demo.py) | Seeds the demo chats (noise scenario). `--report` prints the measured table |
| [scripts/mock_llm.py](scripts/mock_llm.py) | Deterministic fake OpenAI-style server, so the demo runs with no API key or network. It logs every request, so you can show exactly what the model received |
| [scripts/demo_setup.py](scripts/demo_setup.py) | Creates a **separate** instance (ports 8775/18795), mock or real model |
| [scripts/preflight.py](scripts/preflight.py) | PASS/WARN/FAIL checklist before the demo. `--live` checks the real model. Never prints the key |
| [demo.md](demo.md) | The full demo script, commands, numbers and slide outline. **Read this before the review** |

**The headline result** (from the seeded noise scenario): linear sent 471 tokens and 28 unrelated messages. Graph and hybrid sent about 190 tokens with 8 unrelated messages. All three kept the 4 relevant facts, so the claim is **complete AND selective**. Regenerate with `python -m scripts.seed_demo --report`.

---

## 6. Tests (where to point if asked "how do you know it works")

All mirror the package layout. Run with `pytest tests/context_graph tests/command/test_context_command.py tests/config/test_context_graph_config.py tests/scripts`.

| Area | Test file |
|---|---|
| DAG traversal (diamond, root, cycle, isolation, CONTEXT edge, ordering) | `tests/context_graph/test_resolver.py` |
| Engine, budget, legality, fallback | `test_graph_engine.py`, `test_hybrid_engine.py`, `test_loop_hybrid.py` |
| Fork boundary / BRANCH edge | `test_fork_at_node.py`, `tests/webui/test_forking.py` |
| Pruning | `test_prune.py` |
| Embeddings / recall / summaries | `test_embed.py`, `test_recall.py`, `test_summaries.py`, `test_summarize.py` |
| Links | `test_links.py` |
| Workflow never reaches the prompt | `test_workflow.py` |
| Observatory numbers equal the real turn | `test_observatory.py`, `test_turn_record.py` |
| Linear vs graph vs hybrid on recorded data | `test_recorded_comparison.py` |
| `/context` command | `tests/command/test_context_command.py` |
| Config defaults and aliases | `tests/config/test_context_graph_config.py` |
| WebUI | `webui/src/tests/chat-tree.test.ts`, `chat-minimap.test.tsx`, `context-observatory.test.tsx`, `thread-shell.test.tsx` |

Last recorded status (log.md, Phase 11): full pytest 6639 passed, 2 known unrelated failures; ruff clean; basedpyright 0 errors on touched files.

---

## 7. Config reference (`contextGraph` in `config.json`)

| Key | Default | Meaning |
|---|---|---|
| `semanticPool` | `archived` | Where hybrid recall may look: `archived` or `family` |
| `semanticTopK` | 3 | Max similarity hits |
| `semanticMinScore` | unset | Unset means the embedder's own cut-off |
| `recallTokenBudget` | 1500 | Cap on the recalled block |
| `semanticEmbedder` | `auto` | `hash`, `model2vec` or `auto` |
| `graphTokenBudget` | 0 | 0 = whole window. Above 0 turns on relevance pruning |
| `keepRecentTurns` | 2 | Turns always kept when pruning |
| `recordComparison` | true | Store the 3-way comparison per turn (2 extra context builds) |
| `summaryMaxMessages` / `summaryMaxTokens` | 80 / 300 | Limits for `/context summarize` |

---

## 8. Phase history (for "how did you build it")

| Phase | What | Plan doc |
|---|---|---|
| 1 | Context package, `/context` command, UI toggle | log.md |
| 2 | Fork provenance and branching | log.md |
| 3 | **Typed-edge DAG resolution**, graph engine | [docs/PHASE3-PLAN.md](docs/PHASE3-PLAN.md) |
| 3.5 | Chat-tree minimap, send from an earlier node | [docs/PHASE3_5-PLAN.md](docs/PHASE3_5-PLAN.md) |
| 4 | Hybrid retrieval and summaries | [docs/PHASE4-PLAN.md](docs/PHASE4-PLAN.md) |
| 5 | Workflow DAG view | [docs/PHASE5-PLAN.md](docs/PHASE5-PLAN.md) |
| 6 | Context Observatory | [docs/PHASE6-PLAN.md](docs/PHASE6-PLAN.md) |
| 7-11 | Relevance pruning, linking, exact Observatory, LLM summaries, demo kit | [docs/PHASES7-11-PLAN.md](docs/PHASES7-11-PLAN.md) |

Decisions for the owner to revisit are in [docs/REVIEW-LATER.md](docs/REVIEW-LATER.md).

---

## 9. Honest limits (say these before they're asked)

- No real model was run end to end. The demo used a mock LLM. The OpenCode Zen path is unverified until `preflight --live` is run with the key.
- Summary quality from `/context summarize` has not been judged.
- Embeddings are small local models (hashed words or model2vec), not a hosted embedding API. Recall is only as good as that model.
- `recordComparison` costs two extra context builds per turn (diagnostic only).
- Idle chats auto-compact after 15 minutes by default, so the demo config sets `idleCompactAfterMinutes: 0`.
- Known unrelated test failures: `test_mcp_reconnect_crash`, `test_session_location` (and some WebUI load-related flakes, see REVIEW-LATER).
- The `pytest` move into main dependencies in `pyproject.toml` looks accidental (section 3).
