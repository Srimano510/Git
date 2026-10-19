# log.md

Single source of truth for context and task status (see `AGENTS.md`, *Context & Status Tracking*).

- Task markers: `[ ]` todo, `[~]` in progress, `[x]` done, `[!]` failed (with notes).
- Read down to the latest **Change log** record before starting work. Log every file change in the Change log.
- Predecessor: `archive/state-log.md` and `archive/state.md` (deprecated 2026-10-16, git-ignored, skip by default). Phases 1 and 2 below were ported from `state-log.md`.

## Current context

- **Project**: nanobot, extended with a context graph (`nanobot/context_graph/`) and a WebUI context-strategy toggle.
- **Phase 1** (baseline context engine, graph data model, UI toggle): COMPLETE.
- **Phase 2** (graph representation and branching, per [MasterGuide-v3.md](MasterGuide-v3.md)): COMPLETE.
- **Phase 3** (typed-edge DAG context resolution): COMPLETE. Plan: [docs/PHASE3-PLAN.md](docs/PHASE3-PLAN.md).
- **Phase 3.5** (chat-tree minimap, node navigation, send-from-earlier-node branching): COMPLETE, browser-checked with Playwright. Plan: [docs/PHASE3_5-PLAN.md](docs/PHASE3_5-PLAN.md).
- **Phase 4** (hybrid retrieval and summaries): COMPLETE, browser-checked, merged to `master` (PR #14 and polish PR #15). Plan and as-built notes: [docs/PHASE4-PLAN.md](docs/PHASE4-PLAN.md).
- **Phase 5** (workflow DAG, optional): COMPLETE, browser-checked, merged to `master` (PR #16). Plan: [docs/PHASE5-PLAN.md](docs/PHASE5-PLAN.md).
- **Phase 6** (Context Observatory and metrics): IMPLEMENTED on branch `phase6`, uncommitted, browser-checked end to end. Plan: [docs/PHASE6-PLAN.md](docs/PHASE6-PLAN.md).
- **Open tasks**: owner to review and commit Phase 6. Temp test gateway and mock LLM stopped; 0 listening test sockets.

## Tasks

### Phase 1: Baseline Context Engine, Context Graph Data Model & UI Toggle
- [x] Step 1: Create `nanobot/context_graph/` package (`model.py`, `observability.py`, `store.py`, `engines.py`, `__init__.py`)
- [x] Step 2: Integrate Context Engines into `nanobot/agent/loop.py` and add `/context` command in `nanobot/command/builtin.py`
- [x] Step 3: Implement Context Strategy UI toggle in WebUI (`ContextStrategyBadge.tsx`, `ThreadComposer`, `ThreadShell`, `types.ts`)
- [x] Step 4: Write unit tests in `tests/context_graph/` (9/9 pass; 18/18 total smoke tests pass)
- [x] Step 5: Startup verification and final commit (all imports OK, consistent)

### Phase 2: Graph Representation & Branching
- [x] Graph branching implemented and verified (see Phase 2 review below)

### Phase 3: Typed-edge DAG Context Resolution (plan: docs/PHASE3-PLAN.md, rev 2)
- [x] Plan rev 2 approved by owner
- [x] P3-0 Audit: callers were `agent/loop.py`, `session/manager.py` (fork), `command/builtin.py` (only strategy name); WebUI reads only `context_strategy`. No backend route exists for `/context-result`.
- [x] P3-1 Slim `model.py` (address nodes, typed edges, incoming index)
- [x] P3-2 `resolver.py` with tests (diamond, root, cycle, isolation, CONTEXT edge, ordering)
- [x] P3-3 `derive.py`: DAG derived from sessions; walks past fork into grandparents
- [x] P3-4 `GraphContextEngine` on `Session.get_history` (budget, legality, fallback)
- [x] P3-5 Deleted store/sync/LinearContextEngine layer; loop calls `get_history` for linear
- [x] P3-6 Integration test through `ContextBuilder.build_transcript()`
- [x] P3-7 Checks: context_graph 12/12; ruff clean; basedpyright 0 errors on touched files; full pytest 6306 passed, 5 failed (all pre-existing, see docs/REVIEW-LATER.md). WebUI untouched, so bun not run.
- [x] P3-8 Docs: `docs/REVIEW-LATER.md`; `webui/build-errors.txt` kept per owner

### Phase 3.5: Chat-tree minimap and node navigation (plan: docs/PHASE3_5-PLAN.md, approved)
- [x] Owner decisions D1-D5 recorded (D1 React Flow + dagre; D2 one chat family; D3 explicit "branching from here" state; D4 user node = re-ask, assistant node keeps reply; D5 right-side collapsible panel)
- [x] P3.5-0 Fork-at-node contract tests (isolation, BRANCH edge, sibling exclusion) against existing fork code
- [x] P3.5-1 `node_to_fork_args` mapping + tests
- [x] P3.5-2 `build_tree_graph` (ancestors + descendants/siblings) + tests
- [x] P3.5-3 Read-only `GET /api/sessions/{key}/graph` + route test
- [x] P3.5-4 `bun add @xyflow/react @dagrejs/dagre` (local, approved); dagre tree layout + collapse of REPLY runs (unit-tested)
- [x] P3.5-5 `ChatMinimap` component on React Flow (pan/zoom, level-of-detail, built-in MiniMap overview)
- [x] P3.5-6 Click node -> open chat at that message
- [x] P3.5-7 Send from earlier node: fork then send (client orchestration)
- [x] P3.5-8 Checks: ruff clean; basedpyright 0 errors on touched files; full pytest 6457 passed, 5 failed (same pre-existing five); `bun run build` OK; vitest: new tests pass, only pre-existing failures remain (8 in app-layout/thread-shell, see REVIEW-LATER); `bun run lint` has 5 errors, all in earlier Phase 1 code (not touched here)
- [x] P3.5-9 Docs

### Phase 4: Hybrid retrieval (semantic recall) and summaries (plan: docs/PHASE4-PLAN.md, decisions recorded)
- [x] Owner decisions D1-D8 recorded (D1 hashed bag-of-words embeddings; D2 derive per turn, no index file; D3 both pools `archived`/`family`; D4 one synthetic recalled-context message; D5 manual summaries first, LLM later; D6 strategy `hybrid`; D7 small minimap flags now, full version in Phase 6; D8 config default + per-session override)
- [x] P4-0 Audit (read-only). Findings: (1) **Injection point**: `TranscriptInput.session_summary` -> `ContextBuilder.build_system_prompt` appends an "[Archived Context Summary]" section; Phase 4 adds an additive `recalled_context` field and a "[Recalled Context]" section through the same path (a labelled block, so it never splices raw messages; placed last in the system prompt to keep the cacheable prefix stable). (2) `ContextResult` gets an additive `recalled` text field; `loop._build_transcript_input` passes it on. (3) `/context` in `command/builtin.py` lowercases all args, so `summary` text must be parsed from the raw args. (4) Config: root `Config` in `config/schema.py` gets a `context_graph` section; `AgentLoop.__init__`/`from_config` need one new optional parameter. (5) `context_strategy` is read in `loop.py:1912`, `builtin.py`, `webui/session_list_index.py:496`, `webui/session_projection.py:54` (both just pass the string through) and WebUI `ThreadShell`/`types.ts`/`api.ts` (type `ContextStrategy` is `"linear"|"graph"`). (6) No embedding code exists in nanobot. (7) `GraphContextEngine` already excludes archived indices (below `last_archived`) from replay.
- [x] P4-1 `embed.py` (HashEmbedder, cosine) + tests
- [x] P4-2 `recall.py` (candidates, scoring, both pools) + tests
- [x] P4-3 `ContextGraphConfig` section + tests
- [x] P4-4 Summaries store + `/context summary` + tests
- [x] P4-5 Engine `hybrid` path + tests
- [x] P4-6 Loop integration, `/context hybrid [pool]`, `_last_context`, integration test
- [x] P4-7 `/graph` route `context` field + route test
- [x] P4-8 WebUI: third toggle item, minimap markers + legend, vitest
- [x] P4-9 Playwright browser check (AGENTS.md *Browser check*)
- [x] P4-10 Checks: full pytest 6502 passed, 2 failed (unrelated: `test_mcp_reconnect_crash`, `test_session_location`); the other 3 earlier 'pre-existing' failures were stale tests for the additive `context_strategy` attach field and are fixed; ruff clean; basedpyright 0 errors on touched files; vitest 1143 passed, 8 failed (same 8 as before Phase 4); `bun run build` and `bun run lint` clean
- [x] P4-11 Docs

### Phase 5: Workflow DAG (plan: docs/PHASE5-PLAN.md, implemented)
- [x] Owner decisions D1-D4 recorded (D1 real trace of each graph/hybrid turn; D2 last turn only in `_last_workflow`; D3 inside the minimap behind a "Workflow" toggle; D4 context stages only, no new loop timing)
- [x] P5-0 Audit (read-only). Findings: (1) `ContextResult.diagnostics` + `retrieval_ms` + `token_count` already hold everything the trace needs, so the engine is unchanged; (2) `get_ancestor_context` takes `edge_types` (default REPLY/BRANCH/CONTEXT), so new `TRIGGERS`/`FEEDS` edges are never followed by the context engine and double as a topological-order check in tests; (3) `build_session_graph` derives only from `Session.messages` and metadata, so metadata-held workflow nodes cannot reach the prompt; (4) the user message is persisted after the context is built (`_persist_user_message_early`), so the trace stores `at = len(session.messages)` and is anchored at read time to the first user message at index >= `at`; (5) copy the `_last_context` pattern: written in `loop._graph_context`, listed in `_FORK_VOLATILE_METADATA_KEYS` (`session/manager.py`), surfaced by `tree.py::build_tree_graph`, drawn in `ChatMinimap`; (6) subagent turns have `query=None` and no user message, so they record no trace
- [x] P5-1 `EdgeType.TRIGGERS`/`FEEDS` + tests (default traversal ignores them)
- [x] P5-2 `context_graph/workflow.py` `build_workflow` + tests
- [x] P5-3 Guarantee tests: workflow never in prompt, messages or `node_ids`
- [x] P5-4 Loop recording, fork volatility + tests
- [x] P5-5 `/graph` route `workflow` field + route test (route is a pass-through of `build_tree_graph`; the field is tested in `test_tree.py`, no separate route test)
- [x] P5-6 WebUI: toggle, workflow node type, layout, legend, i18n (10 locales) + vitest
- [x] P5-7 Playwright browser check (AGENTS.md *Browser check*) (real hybrid turn via temp gateway + mock LLM; found and fixed re-framing on toggle; gateway and mock stopped, 0 listening test sockets)
- [x] P5-8 Checks: full pytest 6516 passed, 58 skipped, 3 deselected (the two known unrelated: `test_equivalent_workspace_paths_share_one_store`, `test_mcp_reconnect_crash`); ruff clean; basedpyright 0 errors on touched files; vitest 1153/1153 on the second run (the first full run showed 52 failures in one file that did not reproduce, file not captured; likely load-related, see REVIEW-LATER); `bun run build` and `bun run lint` clean
- [x] P5-9 Docs: `log.md`, MasterGuide, `docs/REVIEW-LATER.md`, `docs/DEMO-FEATURES.md`

### Phase 6: Context Observatory and metrics (plan: docs/PHASE6-PLAN.md, implemented)
- [x] Owner decisions D1-D4 recorded (D1 rebuild on demand from the pre-turn snapshot; D2 all three strategies; D3 rewrite the existing drawer in place; D4 seed script writes the merge link, no `/context link`)
- [x] P6-0 Audit (read-only). Findings: (1) `ContextObservatory.tsx` exists from Phase 1 but is broken: calls a non-existent `/context-result` route, sends no bearer token, is mounted with `sessionKey="current"`, hard-coded English, no tests, linear/graph only; (2) the `/graph` route and `session_context_payload` are the pattern for a sanitized route; (3) the HTTP route cannot see the loop's context window or `ContextGraphConfig`, so the loop must record them per turn; (4) the Phase 5 anchor logic (`tree._workflow`) is reusable for the turn's user message; (5) linear replay (`get_history`) keeps a short archived tail (`min(last_archived, recent_start)`) and skips `_command` messages, so linear and graph genuinely differ even in simple chats, and linear node ids must be inferred by the suffix rule; (6) no ranking step exists, so timing is traversal / vector / total
- [x] P6-1 Anchor helper extraction, `_last_turn` recording for every user turn, fork volatility, metrics log line + tests
- [x] P6-2 `context_graph/observatory.py` `build_observatory` + tests
- [x] P6-3 Route `GET /api/sessions/{key}/context-result` + tests
- [x] P6-4 WebUI: rewrite `ContextObservatory.tsx`, `fetchContextResult`, `ThreadShell` wiring, i18n (10 locales) + vitest
- [x] P6-5 `scripts/seed_demo.py` + `docs/DEMO-SCENARIO.md` + slide outline (the script's report: linear 0/4, graph 2/4, hybrid 4/4 relevant; same 12 unrelated messages in all)
- [x] P6-6 Playwright browser check (AGENTS.md *Browser check*) (seeded turn and a real hybrid turn via temp gateway + mock LLM; fixed linear cold-start timing, ambiguous node ids, narrow-width overflow, closed drawer in tab order; dark and 420px checked; test gateway and mock stopped, 0 listening test sockets; the owner's gateway on 18790 left alone)
- [x] P6-7 Checks: full pytest 6532 passed, 58 skipped, 3 deselected (the two known unrelated); ruff clean; basedpyright 0 errors on touched files and the seed script (3 errors found and fixed); vitest 1157/1157 (one earlier full run showed 52 failures in `agent-activity-cluster.test.tsx`, an untouched file, which passes alone 53/53 and passed in the next full run: cold-start/load flake); `bun run build` and `bun run lint` clean
- [x] P6-8 Docs: `log.md`, MasterGuide, `docs/REVIEW-LATER.md`, `docs/DEMO-FEATURES.md`

## Change log

Newest record last. Each record: timestamp, step, what changed, commit, status.

| Timestamp (UTC) | Step | Change | Commit | Status |
| :--- | :--- | :--- | :--- | :--- |
| 2026-09-28T19:27:30Z | Phase 1 start | Session initialized (goal: Phase 1). Start commit | `679199d4d02dcb5202bcc242b8f5cbb67fe84805` | SUCCESS |
| 2026-09-28T19:27:30Z | Phase 1, Step 1 | Create `nanobot/context_graph/` package | `0f2d592c` | SUCCESS |
| 2026-09-28T19:49:51Z | Phase 1, Step 2 | Integrate `loop.py` and `/context` command | `b548ab2e3` | SUCCESS |
| 2026-09-28T19:49:51Z | Phase 1, Step 3 | WebUI Context Strategy toggle | `b548ab2e3` | SUCCESS |
| 2026-09-28T19:57:11Z | Phase 1, Step 4 | Unit tests (9/9) and smoke tests (18/18) | `b548ab2e3` | SUCCESS |
| 2026-09-28T19:57:36Z | Phase 1, Step 5 | Startup verification and final commit | `b548ab2e3` | SUCCESS |
| (undated in state-log) | Phase 2 | Completion review recorded: graph branching verified (details below) | n/a | SUCCESS |
| 2026-10-16T10:22:36Z | Migration | Created `log.md`; ported `state-log.md` content; moved `state-log.md` and `state.md` to `archive/` (`git mv`); added deprecation notice atop `archive/state-log.md`; added `archive/` to `.gitignore` | uncommitted | SUCCESS |
| 2026-10-16 | Phase 3 prep | Installed `uv` into project `.venv` via pip (owner-approved, not global); ran `uv sync --all-extras --dev`; baseline `pytest tests/context_graph` 16 passed | n/a | SUCCESS |
| 2026-10-16 | Phase 3 prep | Added `docs/PHASE3-PLAN.md`; added Phase 3 tasks to `log.md`; `AGENTS.md` Git & Commits: plan in `docs/` then wait for approval, owner commits | uncommitted | SUCCESS |
| 2026-10-16 | Phase 3 prep | Owner answers Q1-Q4 + cut depth; rewrote `docs/PHASE3-PLAN.md` (rev 2: DAG derived from sessions, delete store/sync layer); added project-goal line atop `AGENTS.md` | uncommitted | SUCCESS |
| 2026-10-16 | Phase 3 | Added `resolver.py`, `derive.py`; rewrote `model.py`, `engines.py`, `__init__.py`; deleted `store.py`, `sync.py` and tests `test_store/test_linear_engine/test_model/test_branching`; added `test_resolver.py`, rewrote `test_graph_engine.py` (7 tests); `session/manager.py` fork no longer writes graph id or re-saves source; `agent/loop.py` uses `GraphContextEngine` for graph and `session.get_history` for linear; added `docs/REVIEW-LATER.md` | uncommitted | SUCCESS |
| 2026-10-17 | Phase 3.5 plan | Read-only audit of fork logic (`session/manager.py`, `webui/forking.py`, `context_graph/derive.py`); added `docs/PHASE3_5-PLAN.md`; added Phase 3.5 tasks to `log.md`; split windows moved to `docs/REVIEW-LATER.md`; MasterGuide Phase 3.5 note. No code changed. Finding: send-from-earlier-node does not auto-branch today (fork is an explicit button) | uncommitted | SUCCESS |
| 2026-10-17 | Phase 3.5 plan | Owner answered D1-D5; plan marked APPROVED; D1 changed to React Flow + dagre (least effort, size not a concern); `MasterGuide-v3.md` Phase 3.5 status updated. No code changed | uncommitted | SUCCESS |
| 2026-10-17 | Phase 3.5 impl | Branch `phase3.5`. Backend: `context_graph/tree.py` (`node_to_fork_args`, `build_tree_graph`), `GET /api/sessions/{key}/graph` in `webui/ws_http.py`; tests `test_fork_at_node.py`, `test_tree.py`, route test in `test_websocket_channel.py`. WebUI: `bun add @xyflow/react @dagrejs/dagre` (local, owner-approved); `lib/chat-tree.ts`, `components/thread/ChatMinimap.tsx`, `fetchSessionGraph` in `lib/api.ts`, `ThreadShell.tsx` (Tree button, panel, branch banner, fork-then-send, scroll to turn), `ThreadComposer.tsx` (`prefill` prop), `App.tsx` (`onOpenChat`); tests `chat-tree.test.ts`, `chat-minimap.test.tsx`, 3 cases in `thread-shell.test.tsx`. Env note: vitest needs `NODE_OPTIONS=--localstorage-file=<tmp>` on Node 26 | uncommitted | SUCCESS |
| 2026-10-17 | Phase 3.5 browser check + fixes | Playwright (`playwright-core` in scratchpad, installed Chrome) against an isolated temp gateway. Found and fixed: (1) minimap drew no edges (custom nodes lacked React Flow `Handle`s); (2) overview map and floating buttons overlapped (MiniMap moved to bottom-right, Tree button hidden while panel open); (3) header context-strategy toggle was cosmetic: no transport/metadata passed, saved nothing, always showed `linear`. `ContextStrategyBadge` is now controlled, header and composer share `ThreadShell` state and persist via `/context <strategy>`; removed dead `updateSessionMetadata` (no backend `session.metadata.update` exists); removed 4 of the old `any` lint errors (lint now clean). Verified in browser: both toggles sync and persist; click non-tip node -> banner -> send forks into a new chat with prefix + message. Added test for toggle sync. `AGENTS.md`: added *Browser check* section | uncommitted | SUCCESS |
| 2026-10-17 | Phase 3.5 map UI pass 2 | Seeded a larger test family (10-turn root, 3 branches, 1 nested branch) in the scratchpad temp workspace and inspected the map with Playwright at zoom levels, wide mode, 600px and dark mode. Fixed: overview map showed no node markers and first fit was wrong (nodes now get explicit width/height); default view now frames the end of the active path at readable zoom once per chat (`FocusOnLoad`), refits when width mode changes; folded runs carry `members` so only runs on the active path count as active; LOD thresholds 0.3/0.6; visible edge stroke; React Flow `colorMode` follows app theme; wide mode is 55% of the shell with min 360px (was crushing the chat); below `md` the panel overlays the chat; Tree and Context floating buttons use theme tokens (were unreadable in dark mode) | uncommitted | SUCCESS |
| 2026-10-17 | Phase 3.5 owner feedback round | Map: overview map now small (110x80) and hidden by default with a header toggle; wheel pans vertically, Shift+wheel sideways, Ctrl/Cmd+wheel zooms (`panOnScroll`, `zoomOnScroll=false`). Main UI: the per-message "Branch" button moved into a "More actions" (three dots) menu in `MessageBubble.tsx` (item label stays "Fork"); new i18n key `message.moreActions` in all 10 locales; tests updated (`message-bubble`, `thread-messages`, `thread-shell`) plus overview-toggle test. Verified in Chrome with wheel events and the menu | uncommitted | SUCCESS |
| 2026-10-18 | Phase 4 plan | Read-only audit of `engines.py`, `derive.py`, `resolver.py`, loop call site, memory/summary code, config schema. Added `docs/PHASE4-PLAN.md` (decisions D1-D8, guide deviations, design, tasks P4-0..P4-11, risks); Phase 4 tasks in `log.md`; REVIEW-LATER entries (embedding options considered, deferred items); MasterGuide Phase 4 deviations note and Phase 6 note (replace minimal flags with full Observatory). No code changed | uncommitted | SUCCESS |
| 2026-10-18 | Phase 4 implementation | New: `context_graph/embed.py` (HashEmbedder), `recall.py`, `summaries.py`; `tree.py` refactored (`load_family`, `message_text`, `context` fields); `engines.py` hybrid path (`query`, `hybrid`, `pool`, recalled block, diagnostics); `observability.py` (`recalled`, `kinds()`); `config/schema.py` (`ContextGraphConfig`, `contextGraph`); `agent/context.py` (`recalled_context` + "[Recalled Context]" section); `agent/loop.py` (`context_graph_config`, `_graph_context`, `_last_context`); `session/manager.py` (`_last_context` volatile on fork); `command/builtin.py` (`/context hybrid [pool]`, `/context summary ...`); WebUI: Hybrid toggle item, minimap markers/legend/in-context runs, `TreePayload.context`; docs/configuration.md section. Bugs fixed: `ToolsConfig` import-order (lazy resolve in `ToolsConfig.__init__`), sessions list dropped `context_strategy` (index v9), `/context` had no tests. Tests: embed, recall, summaries, hybrid engine, loop, config, tools-config lazy, context command, session list index, tree, minimap, thread-shell | uncommitted | SUCCESS |
| 2026-10-18 | Phase 4 checks | Full suites run. Fixed stale expectations for the attach payload's `context_strategy` in `tests/webui/test_session_projection.py` and `nanobot/channels/websocket/tests/test_websocket_channel.py`. Results in P4-10 above | uncommitted | SUCCESS |
| 2026-10-18 | Polish pass (branch `polish`) | Restored the original `ThreadHeader.tsx` from before `7c20961c` and re-added the context toggle (the stripped header had dropped theme toggle, prompt navigator, session info, temporary-chat control: these were the 8 'pre-existing' WebUI failures); dropped the stale `sessionKey` prop from the call. `setup.ts` guards undefined `localStorage` (Node 26). Slash-command turns hidden from `tree.py` (edges bridged, tip moved) and excluded from `recall.py`. `derive.py` exposes `fork_of`/`canonical_node`; `summaries.py` resolves ranges canonically (fork prefix maps to source, inherited copies deduped, `Summary.head/nodes`). i18n: `thread.chatTree.*` keys in 10 locales, used in `ChatMinimap`, `ThreadShell`, `ContextStrategyBadge`. New `docs/DEMO-FEATURES.md`. Tests added: recall (`_command`), tree (`_command`), summaries (fork prefix, dedupe). Results: WebUI 1151/1151, build and lint clean; context_graph tests pass | uncommitted | SUCCESS |
| 2026-10-19 | Phase 5 plan | Read-only audit (`engines.py`, `resolver.py`, `derive.py`, `tree.py`, `loop._graph_context`, `session/manager.py` volatile keys, `ChatMinimap`, `chat-tree.ts`). Added `docs/PHASE5-PLAN.md` (decisions D1-D4, guide deviations, design, tasks P5-0..P5-9, risks); Phase 5 tasks in `log.md`; corrected stale Phase 4 status (merged via PR #14/#15); MasterGuide Phase 5 deviations note; REVIEW-LATER Phase 5 planning note. Branch `phase5` from `master`. No code changed | uncommitted | SUCCESS |
| 2026-10-19 | Phase 5 implementation | New: `context_graph/workflow.py` (`build_workflow`, `WORKFLOW_EDGES`); `model.py` (`EdgeType.TRIGGERS`/`FEEDS`); `agent/loop.py` (`_graph_context` records `_last_workflow`, skipped for subagent turns); `session/manager.py` (`_last_workflow` fork-volatile); `tree.py` (`_workflow`, additive `workflow` field with `anchor`); WebUI: `lib/chat-tree.ts` (`WorkflowNode`, `withWorkflow`, layout size), `ChatMinimap.tsx` (Workflow toggle, violet workflow nodes, legend, re-frame on toggle), `thread.chatTree.showWorkflow/hideWorkflow/workflowStep` in 10 locales. Tests: `tests/context_graph/test_workflow.py` (new), `test_tree.py` (workflow field), `chat-minimap.test.tsx` (2 cases). Docs: `docs/PHASE5-PLAN.md` section 6, `docs/DEMO-FEATURES.md`, MasterGuide, REVIEW-LATER. Results in P5-8 above | uncommitted | SUCCESS |
| 2026-10-19 | Phase 6 plan | Branch `phase6` from `master` (Phase 5 merged, PR #16). Read-only audit (`ContextObservatory.tsx`, `ThreadShell` wiring, `ws_http.py` `/graph` and `/context` routes, `session_context.py`, `Session.get_history`, loop strategy selection). Added `docs/PHASE6-PLAN.md` (decisions D1-D4, guide deviations, design, tasks P6-0..P6-8, risks); Phase 6 tasks in `log.md`; MasterGuide Phase 6 deviations note; REVIEW-LATER Phase 6 planning note. No code changed | uncommitted | SUCCESS |
| 2026-10-19 | Phase 6 implementation | New: `context_graph/observatory.py` (`build_observatory`: linear/graph/hybrid rebuilt from the pre-turn snapshot, sanitized DTO); `tree.turn_anchor` (extracted, shared with the Phase 5 workflow field); `agent/loop.py` `_turn_history` (strategy choice moved out of `_build_turn`, records `_last_turn`, logs one `Context strategy=...` line per turn); `session/manager.py` (`_last_turn` fork-volatile); `webui/ws_http.py` route `GET /api/sessions/{key}/context-result`; WebUI: `fetchContextResult` + types in `lib/api.ts`, `ContextObservatory.tsx` rewritten (token, real chat key, theme tokens, i18n `thread.observatory.*` in 10 locales), `ThreadShell` mounts it only for a saved chat; `scripts/seed_demo.py`, `docs/DEMO-SCENARIO.md`. Tests: `test_turn_record.py`, `test_observatory.py`, `test_seed_demo.py` (new), route test in `test_websocket_channel.py`, `context-observatory.test.tsx` (new). Docs: `docs/PHASE6-PLAN.md` section 6, DEMO-FEATURES, MasterGuide, REVIEW-LATER. Results in P6-7 above | uncommitted | SUCCESS |
| 2026-10-19 | Phase 6 refinement (owner screenshot) | Owner's Observatory showed `Fell back: ValueError: graph produced no legal replay` for Graph and Hybrid. Diagnosed with a structure-only script on the owner's chat (no message text printed): 5-deep fork chain, all ancestors compacted, only `_command` turns left after the archive pointer. Bug in `context_graph/engines.py`: `_command` turns counted as replayable but dropped by `get_history` (empty history -> raise -> linear fallback, hybrid recall skipped; node ids shifted by mid-replay commands). Fix: exclude `_command` from the replayable set. Tests: 3 in `test_graph_engine.py`, 1 in `test_observatory.py` (written first, failed, then passed). UI: fallback text readable in dark (`ContextObservatory.tsx`), node id labels (`#n` / `…tag#n`, title = full id), fallback card counts the linear history it fell back to (`observatory.py`); vitest +2. Playwright on a temp gateway: synthetic scenario and forced fallback checked in light/dark; servers stopped, 0 listening test sockets. Results: full pytest 6536 passed, 58 skipped, 3 deselected (the two known unrelated); ruff clean; basedpyright 0 errors on `context_graph`; vitest 1159/1159 on the final full run (an earlier full run failed 53 tests in 2 files, `agent-activity-cluster.test.tsx` (untouched, passes alone 53/53) plus one more, and the next full run was green: the known load-sensitive flake, see REVIEW-LATER); `bun run build` and `bun run lint` clean | uncommitted | SUCCESS |

## Phase 1 Final Delivery Record
- **Start commit**: `679199d4d02dcb5202bcc242b8f5cbb67fe84805`
- **End commit**: `b548ab2e3`
- **Files changed**: 15 files, 449 insertions, 4 deletions
- **New**: `nanobot/context_graph/` (5 files), `tests/context_graph/` (3 test files), `webui/src/components/thread/ContextStrategyBadge.tsx`
- **Modified**: `loop.py`, `builtin.py`, `ThreadComposer.tsx`, `ThreadShell.tsx`, `types.ts`

## Phase 2 Completion Review
- **Objective**: Graph Representation and Branching per [MasterGuide-v3.md](MasterGuide-v3.md)
- **Status**: COMPLETE
- **Verification evidence**:
  - [nanobot/context_graph/model.py](nanobot/context_graph/model.py) defines `EdgeType.BRANCH`, supports multiple children on a node, preserves branch edges through serialization, and implements `ConversationGraph.add_branch()`.
  - [nanobot/context_graph/sync.py](nanobot/context_graph/sync.py) records fork boundaries and child-session provenance, and creates `BRANCH` edges when a child session diverges from a parent session.
  - [nanobot/context_graph/engines.py](nanobot/context_graph/engines.py) synchronizes graph state and tracks branch counts while keeping the baseline linear replay semantics intact.
  - [webui/src/components/MessageBubble.tsx](webui/src/components/MessageBubble.tsx) includes the copy action and a fork/branch control; [webui/src/components/thread/ThreadMessages.tsx](webui/src/components/thread/ThreadMessages.tsx) and related thread UI components handle the fork-from-message flow.
  - [tests/context_graph/test_branching.py](tests/context_graph/test_branching.py) covers multi-branch support, idempotent branch records, round-tripping, and historical fork persistence.
- **Conclusion**: Phase 2 graph branching requirements are implemented and validated (persistent graph state and fork provenance), not stubbed.
