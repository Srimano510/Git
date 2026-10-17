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
- **Phase 4** (hybrid retrieval and summaries): PLAN WRITTEN on branch `phase4`, owner decisions D1-D8 recorded, waiting for the owner to commit the docs. No code yet. Plan: [docs/PHASE4-PLAN.md](docs/PHASE4-PLAN.md).
- **Open tasks**: owner to commit the Phase 4 docs; then start P4-0 (read-only audit).

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
- [ ] P4-0 Audit (read-only): summary injection point, `/context` arg parsing, config placement, callers of `GraphContextEngine`/`context_strategy`
- [ ] P4-1 `embed.py` (HashEmbedder, cosine) + tests
- [ ] P4-2 `recall.py` (candidates, scoring, both pools) + tests
- [ ] P4-3 `ContextGraphConfig` section + tests
- [ ] P4-4 Summaries store + `/context summary` + tests
- [ ] P4-5 Engine `hybrid` path + tests
- [ ] P4-6 Loop integration, `/context hybrid [pool]`, `_last_context`, integration test
- [ ] P4-7 `/graph` route `context` field + route test
- [ ] P4-8 WebUI: third toggle item, minimap markers + legend, vitest
- [ ] P4-9 Playwright browser check (AGENTS.md *Browser check*)
- [ ] P4-10 Checks (pytest, ruff, basedpyright, bun test/build/lint)
- [ ] P4-11 Docs

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
