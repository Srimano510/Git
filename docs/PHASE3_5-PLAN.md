# Phase 3.5 plan: chat-tree minimap and node navigation

Status: **IMPLEMENTED 2026-10-17 on branch `phase3.5`, uncommitted. All tasks P3.5-0 to P3.5-9 done; see log.md. Not yet tried by hand in a browser.**
Position: after Phase 3 (typed-edge DAG resolution), before Phase 4. Phase 6 (Observatory) will reuse the minimap.
Governing rule ([AGENTS.md](../AGENTS.md)): minimum code, reuse existing structure. This phase widens scope from the DAG to the WebUI, so it needs the owner's explicit agreement (section 1).

## 1. Scope

In:
1. A **minimap** of the whole chat tree (all forks of a chat family), combining three ideas (built on React Flow, decision D1):
   - **Pan/zoom canvas** is the main view, with zoom-dependent detail: dots when zoomed out, one-line preview at mid zoom, full message when zoomed in.
   - **Collapsible runs:** a linear stretch of REPLY nodes folds into one "+N messages" node. Branch points always stay visible.
   - **Overview + detail:** a small corner minimap with a viewport rectangle (VS Code style), expandable to the full canvas.
2. **Click a node to move there** (scroll/open the chat at that message).
3. **Send from an earlier node auto-branches** (section 3).

Out (moved to [REVIEW-LATER.md](REVIEW-LATER.md)): split windows / multiple chats side by side.

Node encoding: colour by role; marker by edge type (REPLY, BRANCH, CONTEXT); ring on the active path. Phase 6 can add a "used in context" highlight.

## 2. Findings from the Phase 2 / 3 audit (done, read-only)

| Question | Finding |
|---|---|
| Does a fork primitive exist? | Yes. `SessionManager.fork_session_before_user_index(source, target, before_user_index, include_user_message)` ([manager.py:1885](../nanobot/session/manager.py)) copies the prefix into a new session and writes the three `context_graph_*` fork metadata keys. WebUI reaches it via the `fork_chat` websocket command ([forking.py](../nanobot/webui/forking.py)); client method `forkChat` in `webui/src/lib/nanobot-client.ts`. |
| Does sending from an earlier point auto-branch today? | **No.** Sending always appends to the tip of the open chat. Forking is an explicit button on a message, and the user then types in the new chat. Phase 2 covers "branch button", not "rewind and send". |
| Can the backend already express "branch at node X"? | Mostly. A node is `(session_key, message index)`. Fork takes a **user-message index** instead, so a small pure mapping is needed: user node k -> `before_user_index=k` (re-ask); assistant node -> index of next user message with the reply included. |
| Is there data for a whole-tree view? | **Partly.** `derive.build_session_graph` walks only *up* from one session (ancestors). A minimap needs *down* too (siblings and descendants), i.e. all sessions whose `context_graph_source_session_key` leads to the same root. Nothing builds that yet. |
| Backend route for graph data? | None. `ws_http.py` has `/api/sessions/{key}/context` etc.; a new read-only `/api/sessions/{key}/graph` fits that pattern. |

## 3. Auto-branch design (backend first)

Decision to confirm: **auto-branch = frontend orchestration of existing commands, no new backend write path.**

Flow: user selects node N in the minimap (the chat view moves to N, composer shows "branching from N") -> on send, the client calls `fork_chat` with the mapped index, attaches to the new chat, then sends the message there. If N is the tip, no fork; the message appends as today.

Backend work is limited to:
- `node_to_fork_args(session, node_index) -> (before_user_index, include_user_message)` pure function, tested.
- Tests proving the behaviour (written first, expected to pass against existing fork code; they pin the contract):
  1. Fork at a mid-chat node, then append a turn to the child: source messages are unchanged (isolation).
  2. The derived DAG has a BRANCH edge from the fork node to the child's first new message, and the source keeps its own REPLY continuation.
  3. Graph-mode context for the child contains the prefix and excludes the sibling's later messages.
  4. Mapping covers user node, assistant node, first message, last message (tip), and a hidden/tool message (rejected or snapped).

## 4. Tasks (mirrored in [log.md](../log.md)); all test-first, each with a done-when

| ID | Task | Done when |
|---|---|---|
| P3.5-0 | Tests for fork-at-node contract (section 3, items 1-3), against existing code | tests pass; any gap found is logged as a bug with a regression test |
| P3.5-1 | `node_to_fork_args` + tests (item 4) | all index cases pass |
| P3.5-2 | `build_tree_graph(root_session, list_sessions)`: ancestors + all descendants/siblings, returns nodes (id, role, short preview, session key) and typed edges | diamond-free tree, 3-level fork, two siblings, orphaned source handled |
| P3.5-3 | Read-only route `GET /api/sessions/{key}/graph` in `ws_http.py` | route test in `test_websocket_http_routes.py`; unknown key -> 404; no write side effects |
| P3.5-4 | `bun add @xyflow/react @dagrejs/dagre` in `webui/` (local only, D1). Data hook + tree layout via dagre; collapse of REPLY runs (pure TS, unit-tested) | vitest: collapse keeps branch points; layout deterministic; `.gitignore` and lockfile reviewed |
| P3.5-5 | `ChatMinimap` component on React Flow: pan/zoom, level-of-detail node rendering, built-in `MiniMap` as the corner overview, expand button | vitest render + interaction tests; `bun run build` green |
| P3.5-6 | Click node -> open that chat and scroll to the message; selected node shown in composer | vitest on `ThreadShell`/`ThreadViewport` wiring |
| P3.5-7 | Send-from-earlier-node: fork then send (client orchestration) | vitest with mocked client: fork called with mapped args, message goes to the new chat; tip send does not fork |
| P3.5-8 | Checks | context_graph and session tests, then full `pytest`; `ruff check nanobot/`; `basedpyright` on touched files; `bun run test`, `bun run build` |
| P3.5-9 | Docs | `log.md`, MasterGuide Phase 3.5 note, `docs/REVIEW-LATER.md`, README/webui docs if user-visible |

## 5. Decisions (all answered by the owner, 2026-10-17)

| # | Decision | Outcome |
|---|---|---|
| D1 | Dependencies | Owner: "whatever takes less effort and time to build; size is no issue". **Use React Flow (`@xyflow/react`)** for pan/zoom, nodes, edges and the built-in `MiniMap`, plus `@dagrejs/dagre` for tree layout (React Flow has no auto-layout). Installed locally with `bun add` inside `webui/` only. This is the owner-approved dependency addition; log it in `log.md` when installed and review `.gitignore`/lockfile. Replaces the earlier "no new library" recommendation. |
| D2 | Tree scope | One chat family: root plus every fork, recursively. |
| D3 | Auto-branch UX | Selecting a past node puts the composer into an explicit "branching from here" state with a cancel. |
| D4 | Branch on user node | User node = re-ask: the fork excludes that message and the composer is pre-filled with it. Assistant node keeps its reply. |
| D5 | Minimap placement | Right-side collapsible panel in the thread view. |

## 6. Risks

- Each fork is a separate session/chat, so "moving between nodes" across branches means switching the active chat, not just scrolling. Hydration of the target chat must be fast and must not lose unsent composer text.
- Large trees: collapse plus level-of-detail are in scope for this reason; virtualised rendering is not, and is recorded only if testing shows a problem.
- Compacted or trimmed prefixes: nodes below the compaction pointer may still exist in storage but not in the visible thread; the minimap shows them dimmed.
- Graph and linear contexts look the same in simple chats (see REVIEW-LATER). The minimap makes that visible; it does not change it.
- The `/context-result` route used by `ContextObservatory.tsx` still has no backend. Out of scope here (Phase 6).

## 7. Implementation notes (as built)

- Backend: `nanobot/context_graph/tree.py` holds `node_to_fork_args` and `build_tree_graph`. Each node carries `fork_before_user_index` (so the UI contains no index logic) and, for user nodes, the full `text` for re-ask prefill. Route: `GET /api/sessions/{key}/graph`.
- The fork-at-node tests (P3.5-0) passed against the existing fork code without changes, so no Phase 2 bug was found. The mapping is simple: every node maps to the count of visible user messages before it, with no include-user flag, because "re-ask" and "keep the turn" both reduce to "stop before the next user message".
- WebUI: `ChatMinimap` (React Flow, dagre, level of detail by zoom, built-in MiniMap, expand toggle). Selecting a node opens its chat, scrolls to the matching prompt, and arms the "Branching from ..." banner; the next send forks, then reuses the existing queued-first-message path to deliver the message in the new chat. Selecting a tip clears the branch.
- Clicking a folded "+N messages" node expands it.
