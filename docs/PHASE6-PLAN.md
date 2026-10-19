# Phase 6 plan: Context Observatory and metrics (demo preparation)

Status: **PLANNED 2026-10-19, decisions D1-D4 recorded, waiting for owner approval to implement.** No code changed.
Branch: `phase6` (from `master` after the Phase 5 merge). Spec: [MasterGuide-v3.md](../MasterGuide-v3.md), "Phase 6" (guide text is partly out of date, see section 2).
Governing rule ([AGENTS.md](../AGENTS.md)): minimum code, reuse the existing structure; the typed-edge DAG stays the only new core idea. Phase 6 only *shows* what the three strategies do, side by side.

## 1. Decisions (owner answers, 2026-10-19)

| # | Decision | Outcome |
|---|---|---|
| D1 | Where the comparison comes from | **Rebuilt on demand from the pre-turn snapshot.** A new route rebuilds linear, graph and hybrid for the last turn from the chat truncated to before that turn's user message (the Phase 5 `at` idea). The agent loop only records one small additive field per turn; no extra per-turn work. The view says it is a reconstruction. |
| D2 | Strategies compared | **All three** (linear, graph, hybrid): one node matrix with a column per strategy, plus per-strategy tokens, nodes and ms. |
| D3 | UI | **Rewrite the existing drawer in place** (`ContextObservatory.tsx`, its floating "Context" button): real route, auth token, the active chat's key, i18n, three strategies, timing bars, tests. |
| D4 | Demo merge | **Seed script writes the merge link** (`CONTEXT` edge in session metadata). No `/context link` command. |

## 2. What changed since the guide was written

| Guide says | Now |
|---|---|
| "Fetch the last `ContextResult` from both engines after each query" | No stored results. The loop runs only the selected engine. The Observatory rebuilds all three on demand from a pre-turn snapshot (D1); only the selected strategy ever feeds the provider, so the comparison cannot change the answer. |
| Linear vs Graph | Linear, Graph and Hybrid (D2). |
| `relevant_count` / `irrelevant_count` per query | Needs ground truth. The product reports "only in X" counts; relevant/irrelevant counts are computed only for the scripted demo, whose seed script knows which messages are relevant (no product code). |
| Ranking time in the breakdown | There is no separate ranking step: traversal = `retrieval_ms - embed_ms`, vector = `embed_ms`, total = `retrieval_ms` (same split as Phase 5). |
| Log `Strategy / Nodes / Tokens / Time` per query | One `loguru` line per turn, for all three strategies, from the loop. |
| Slide outline, demo scenario | Docs only: `docs/DEMO-SCENARIO.md` + `scripts/seed_demo.py`. |

Facts found in the code that shape the design:
- **`ContextObservatory.tsx` already exists (Phase 1) but is broken and unwired:** it calls `/api/sessions/{key}/context-result`, which has no backend route; sends no bearer token; is mounted with `sessionKey="current"` in `ThreadShell` (a literal, not the chat key); has hard-coded English text, no tests, and knows only linear/graph. It also uses fixed `bg-white` classes instead of theme tokens.
- **Sanitized-projection pattern already exists:** `webui/session_context.py::session_context_payload` and the `/graph` route in `webui/ws_http.py` (`check_api_token`, key decode, websocket-key check, `asyncio.to_thread`). The new route copies the `/graph` route.
- **The route has no access to the agent loop's settings** (context window, `ContextGraphConfig`). So the loop records them per turn; the route rebuilds with exactly the budget and config the turn used.
- **Phase 5 gave the anchor:** the user message of the turn is the first visible user message at index `>= at` (`tree._workflow` already finds it). That logic is reused, not copied.
- **Linear replay differs from graph replay** by design: `Session.get_history` starts at `min(last_archived, recent_start)`, i.e. it keeps a short archived tail, and skips `_command` messages. The matrix will therefore show genuine differences even in simple chats.
- `_last_context` (Phase 4) and `_last_workflow` (Phase 5) stay as they are (published contracts only grow); the Observatory does not depend on them.

## 3. Design

### 3.1 Recording (`agent/loop.py`, `session/manager.py`)
- For every user turn (not subagent turns), whatever the strategy, the loop writes `session.metadata["_last_turn"] = {"strategy", "at": len(session.messages), "max_tokens": context_window_tokens, "graph_config": context_graph_config.model_dump()}` (volatile on fork: added to `_FORK_VOLATILE_METADATA_KEYS`).
- One metrics log line per turn: `Context strategy=<s> nodes=<n> tokens=<t> ms=<x>` (and `recall hits=<h>` for hybrid), built from the `ContextResult` for graph/hybrid and from the replayed history for linear. Tokens use the existing `estimate_message_tokens`.

### 3.2 Rebuild and compare (`nanobot/context_graph/observatory.py`, pure)
`build_observatory(key, load_session, list_sessions) -> dict | None`:
1. Read `_last_turn`; find the anchor user message (shared helper extracted from `tree._workflow`); no record or no anchor -> `None`.
2. Snapshot = the session truncated to `messages[:at]` (same metadata, same `last_archived`, clamped to `at`); query = the anchor message text.
3. Run the three strategies on that snapshot: linear via `Session.get_history(max_tokens=0, extend_to_user=False)` exactly as the loop does, graph and hybrid via `GraphContextEngine` with the recorded `max_tokens`, config and the session's `context_pool`. Each is timed; any exception becomes that strategy's `fallback` text instead of failing the whole payload.
4. Return the **sanitized DTO** (no raw session data, no runtime-context blocks, no paths or provider state; excerpts come from the public form of each message, truncated):

```
{"at": 12, "selected": "hybrid", "reconstructed": true, "query": "<excerpt>",
 "strategies": {"linear": {"nodes": 8, "tokens": 640, "ms": 0.3, "fallback": null,
                           "timing": {"traversal_ms": 0.3, "vector_ms": 0, "total_ms": 0.3}},
                "graph": {...}, "hybrid": {... "recalled": 2, "summaries": 0}},
 "nodes": [{"id": "websocket:a#3", "role": "user", "excerpt": "...", "tokens": 12,
            "in": {"linear": true, "graph": true, "hybrid": true},
            "reason": {"graph": "reply", "hybrid": "vector (score 0.42)"}}],
 "only": {"linear": 1, "graph": 0, "hybrid": 2}}
```
Linear node ids map to the last *n* non-`_command` messages of the replayed range (the same suffix rule the graph engine already uses), documented as a limit.

### 3.3 Route (`webui/ws_http.py`)
`GET /api/sessions/{key}/context-result`: same guards as `/graph` (token, key decode, websocket-key check, session manager present); 404 when the session is unknown **or has no recorded turn**; payload computed in `asyncio.to_thread`. Keyed by session key, so panes and chats cannot see each other's data. Metrics survive a page refresh because the source is the saved session, not browser state.

### 3.4 UI (`ContextObservatory.tsx`, rewritten in place)
- Props: `token`, `sessionKey` (the real chat key; `ThreadShell` passes it instead of `"current"`), `open`, `onClose`, `refreshKey`. `fetchContextResult(token, key)` goes in `lib/api.ts` with the existing auth pattern; the inline fetch is removed.
- Sections: (a) one card per strategy: nodes, tokens, ms, token bar, fallback badge, "used for this turn" mark on the selected one; (b) timing view (traversal / vector / total, text plus bars); (c) node matrix: id, role, excerpt, tokens, L/G/H marks, per-strategy reason; a "differences only" filter and "only in X" counts; (d) a line stating the data is rebuilt from the state before the last turn.
- Empty (no turn yet or linear chat before any turn) and error states; theme tokens (`bg-background`, `text-foreground`), works in dark mode and at phone width; all text under `thread.observatory.*` in the 10 locale files (machine-translated, same caveat as before).
- The floating "Context" button stays; text moves to i18n.

### 3.5 Demo (`scripts/seed_demo.py`, `docs/DEMO-SCENARIO.md`)
- Script seeds a repeatable family in a chosen workspace: a root chat (project talk plus unrelated chatter, partly archived), a fork for a side topic (graph vs vector), and a **merge** as a `CONTEXT` edge in the fork's metadata (D4); `--report` prints the three-strategy comparison from `build_observatory` and relevant/irrelevant counts against the script's own list of relevant messages.
- Doc: the scripted conversation, what each strategy should include and why, the Observatory screenshots, and the slide outline from the guide (Problem, linear limits, graph representation, engine architecture, phases, demo comparison, metrics, conclusion).

### 3.6 Not doing
- No per-turn history of comparisons, no export/CSV, no live streaming of metrics, no `/context link` command, no change to `ContextResult`, the engines or the resolver, no real ranking step, no multi-pane UI beyond keying by session.

## 4. Tasks (mirrored in [log.md](../log.md)); test-first, each with a done-when

| ID | Task | Done when |
|---|---|---|
| P6-0 | **Audit (read-only)** | done in this plan (section 2); findings table in `log.md` |
| P6-1 | Shared anchor helper (extracted from `tree._workflow`) + `_last_turn` recording for every user turn + fork volatility + metrics log line + tests | linear, graph and hybrid user turns record `_last_turn`; subagent turns do not; forks drop it; existing Phase 5 tree tests still pass; log line asserted with a log capture |
| P6-2 | `observatory.py` `build_observatory` + tests | three strategies rebuilt from the pre-turn snapshot (a later reply is not in the result); diff marks and "only" counts correct (guide diff test); one failing strategy shows its `fallback` and the others still return; excerpts truncated and runtime-context text absent; `None` without a record; empty-chat edge |
| P6-3 | Route `GET /api/sessions/{key}/context-result` + tests | 401 without token, 404 unknown session or no turn, 200 payload for a seeded chat; two chats never return each other's nodes; second request after "refresh" returns the same data |
| P6-4 | WebUI: `fetchContextResult`, rewrite `ContextObservatory.tsx`, `ThreadShell` passes token and real key, i18n (10 locales) + vitest | cards, matrix, differences-only filter, empty and error states, auth header and real key asserted; build and lint clean |
| P6-5 | Seed script + `docs/DEMO-SCENARIO.md` + slide outline | script runs on a temp workspace and `--report` prints three strategies with the expected differences (merge-only node in graph, archived fact only in hybrid) |
| P6-6 | Playwright browser check (AGENTS.md *Browser check*): seeded family on a temp gateway with mock LLM, open the Observatory for each of the three strategies, dark mode and narrow width, screenshots | screenshots reviewed; temp gateway and mock stopped, 0 listening test sockets |
| P6-7 | Checks: touched tests, full `pytest`, `ruff`, `basedpyright` on touched files, `bun run test/build/lint` | green apart from the two known unrelated failures in REVIEW-LATER |
| P6-8 | Docs: `log.md`, MasterGuide (Phase 6 deviations), `docs/REVIEW-LATER.md`, `docs/DEMO-FEATURES.md`, README/config docs only if user-visible config changed (none planned) | updated |

Files expected to change: new `context_graph/observatory.py`, `tests/context_graph/test_observatory.py`, `scripts/seed_demo.py`, `docs/DEMO-SCENARIO.md`; edited `context_graph/tree.py` (helper extraction), `agent/loop.py` (record + log line), `session/manager.py` (one set entry), `webui/ws_http.py` (route) and its test file, `webui/src/lib/api.ts`, `ContextObservatory.tsx`, `ThreadShell.tsx`, 10 locale files, and the tests that mirror them. "Memory and sessions" and "Message bus and agent core" rows of AGENTS.md apply: the full `pytest` is required, fields are additive.

## 5. Risks and honest caveats

- **It is a reconstruction, not a recording.** If compaction ran after the turn, the rebuilt linear/graph/hybrid contexts can differ from what the model actually received. The selected strategy's mark and the on-screen note say so; D1 traded exactness for zero per-turn cost. (The Tree's `_last_context` flags remain the exact record for graph/hybrid turns.)
- **Timings are of the rebuild**, not of the original turn, and `traversal_ms` includes loading the sessions the graph touches (as in Phase 5). Linear is near zero by construction; do not read the bars as a fair speed benchmark.
- **Linear node ids are inferred** (suffix rule); a mid-range `_command` message could shift an id by one. Covered by a test for the common case; noted in REVIEW-LATER.
- **Hybrid reconstruction depends on the saved `context_pool` and recorded config.** If the owner changes the pool after the turn, the rebuild uses the *current* session pool override but the *recorded* config defaults.
- **The family pool loads every session** each time the Observatory is opened (as in `/graph`); fine for a demo.
- **`recall_count` in the logs is `semantic_hits`**, a count of matches, not a quality score; "relevant" is only known in the scripted demo.
- **The seed script is a demo aid**, not product code; it writes into whatever workspace it is pointed at, so it refuses to run without an explicit path argument.
- **Machine-translated labels** again in 9 locales.
