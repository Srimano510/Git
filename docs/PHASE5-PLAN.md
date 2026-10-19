# Phase 5 plan: workflow DAG (operation nodes)

Status: **PLANNED 2026-10-19, decisions D1-D4 recorded, waiting for owner approval to implement.** No code changed.
Branch: `phase5` (from `master` after the Phase 4 and polish merges). Spec: [MasterGuide-v3.md](../MasterGuide-v3.md), "Phase 5" (optional phase; guide text is partly out of date, see section 2).
Governing rule ([AGENTS.md](../AGENTS.md)): minimum code, reuse the existing structure; the typed-edge DAG stays the only new core idea. Phase 5 only applies the same typed-edge idea to *how a turn's context was built*, as an observability record.

## 1. Decisions (owner answers, 2026-10-19)

| # | Decision | Outcome |
|---|---|---|
| D1 | Source of workflow nodes | **Real trace of each graph/hybrid turn**, built from the `ContextResult` the turn already produced (strategy, traversal counts, vector search, summaries, token count, real ms). Not a simulated sample. Linear turns record nothing (the engine is not involved). |
| D2 | History kept | **Last turn only**: `session.metadata["_last_workflow"]`, same pattern as `_last_context`; dropped on fork. |
| D3 | UI | **Inside the existing minimap, behind a "Workflow" toggle**: different colour, hanging off the user message of that turn. Reuses React Flow, dagre layout and the legend. Phase 6 Observatory can absorb it. |
| D4 | Loop touch | **Context stages only.** No new timing in the agent loop; `PromptBuild` and `LLMCall` appear as nodes without a duration. The only loop change is recording the trace next to `_graph_context`'s existing `_last_context` line. |

## 2. What changed since the guide was written

| Guide says | Now |
|---|---|
| Add `WorkflowNode` or reuse `ChatNode`; store in `ConversationGraph` / "graph sidecar" | No `ChatNode` and no sidecar store exist (Phase 3). Nodes are addresses `(group, index)`. Workflow nodes reuse `NodeId` with group `"workflow"` and the existing `ConversationGraph`; message nodes are never touched. |
| Edge types `INTENT`, `TRIGGERS`, `FEEDS` | Two new `EdgeType` members, `TRIGGERS` and `FEEDS`. `INTENT` is dropped (nanobot has no intent-analysis step; "strategy selection" plays that role). |
| Sample flow `Intent -> MemorySearch + WebSearch -> Merge -> PromptBuild -> LLMCall` | The repo-specific flow from the guide's own implementation note, trimmed to what really runs (section 3.1). No web search, no intent model. |
| "Log the execution order and time of simulated tasks" | Real durations for the stages we already measure (`retrieval_ms`, `embed_ms`); the order is the DAG's topological order. |
| Storage "linked by `turn_id`, `message_id`" | Linked by position: the turn's user message (section 3.3). Neither id is stored on messages today. |

Facts found in the code that shape the design:
- `GraphContextEngine.build_context` already returns everything a trace needs in `ContextResult.diagnostics` (`visited`, `returned`, `pruned`, `branch_count`, `semantic_candidates`, `semantic_hits`, `semantic_included`, `summaries_used`, `embed_ms`, `semantic_error`, `fallback`) plus `retrieval_ms`, `token_count`. No engine change is needed to *produce* the trace.
- `get_ancestor_context(graph, node, edge_types)` takes the edge types to follow and defaults to `{REPLY, BRANCH, CONTEXT}`. A workflow edge is therefore never followed by the context engine, by construction. It also returns a topological order, which the tests reuse to prove the execution order.
- `build_session_graph` derives the message DAG from `Session.messages` and metadata only, so a workflow trace in metadata can never enter `ContextResult.messages`.
- The user message is persisted after the context is built (`_persist_user_message_early` runs later in `_prepare_turn`), so its index is not known when the trace is recorded. The trace stores `at = len(session.messages)` and the first user message at index `>= at` is its anchor at read time.
- `_last_context` is the model to copy: written in `loop._graph_context`, listed in `_FORK_VOLATILE_METADATA_KEYS` (`session/manager.py`), surfaced as an additive field by `build_tree_graph`, drawn by `ChatMinimap`.

## 3. Design

### 3.1 Workflow nodes and edges (`nanobot/context_graph/workflow.py`, pure)

`build_workflow(result: ContextResult, at: int) -> dict` returns a JSON-safe record:

```
{"at": 12, "strategy": "hybrid",
 "nodes": [{"id": "workflow#0", "type": "intent", "label": "Strategy", "detail": "hybrid, pool=archived"}, ...],
 "edges": [{"source": "workflow#0", "target": "workflow#1", "type": "TRIGGERS"}, ...]}
```

| # | Label | `type` | When | Detail (real values) | ms |
|---|---|---|---|---|---|
| 0 | `ContextStrategySelection` | `intent` | always | strategy, pool | - |
| 1 | `GraphTraversal` | `tool` | always | visited / returned / pruned / branches; `fallback` if it fell back | `retrieval_ms - embed_ms` |
| 2 | `SemanticSearch` | `tool` | hybrid only | candidates / hits / included / summaries used, or `semantic_error` | `embed_ms` |
| 3 | `ContextMerge` | `merge` | always | nodes in context, recalled included | - |
| 4 | `PromptBuild` | `prompt` | always | token count | - |
| 5 | `LLMCall` | `execution` | always | - | - |

Edges: `0 -TRIGGERS-> 1`, `0 -TRIGGERS-> 2` (hybrid), `1 -FEEDS-> 3`, `2 -FEEDS-> 3`, `3 -FEEDS-> 4`, `4 -FEEDS-> 5`. Nodes 1 and 2 are the parallel branch of the guide's sample. The workflow is built as a `ConversationGraph` of `("workflow", i)` addresses with the two new `EdgeType`s, then serialised, so the order check in tests is `get_ancestor_context(g, ("workflow", 5), WORKFLOW_EDGES)`.

### 3.2 Keeping workflow nodes out of the prompt (the guide's failure mode)
Three independent guarantees, each tested:
1. Never written to `Session.messages`.
2. Never added to the graph `build_session_graph` returns.
3. `TRAVERSE_EDGE_TYPES` excludes `TRIGGERS` and `FEEDS`, so even a mixed graph would not follow them.

### 3.3 Recording and reading
- `agent/loop.py::_graph_context`: after the existing `_last_context` line, `session.metadata["_last_workflow"] = build_workflow(result, len(session.messages))`, only when `query is not None` (subagent turns have no user message to anchor to).
- `session/manager.py`: add `"_last_workflow"` to `_FORK_VOLATILE_METADATA_KEYS`.
- `context_graph/tree.py::build_tree_graph`: additive `workflow` field next to `context`: the record's nodes and edges plus an `anchor` (first visible user node at index `>= at` in the requested session) and a `TRIGGERS` edge `anchor -> workflow#0`. Absent when there is no record or no anchor.

### 3.4 UI (`ChatMinimap`, small)
- `TreePayload.workflow?`; a "Workflow" toggle button in the panel header (shown only when the payload has a workflow), off by default.
- When on: the anchor user node is exempt from run folding, workflow nodes/edges are appended before `layoutTree` (new `kind: "workflow"` size), rendered by a small `workflow` node type (colour distinct from the message roles, shows label, detail and ms), and a legend entry names the colour.
- Labels in `en` and the other 9 locale files (`thread.chatTree.workflow*`), as in the polish pass.
- Phase 6 replaces this with the Observatory.

### 3.5 Not doing
- No per-turn history, no workflow editing from the UI, no real intent analysis, no web/memory search nodes, no timing of PromptBuild/LLMCall, no `/context workflow` command, no change to `ContextResult`, the engine or the resolver's defaults.

## 4. Tasks (mirrored in [log.md](../log.md)); test-first, each with a done-when

| ID | Task | Done when |
|---|---|---|
| P5-0 | **Audit (read-only)** of the injection points above | done in this plan (section 2); findings table in `log.md` |
| P5-1 | `EdgeType.TRIGGERS` / `FEEDS` (`WORKFLOW_EDGES` set lives in `workflow.py`); test that the default traversal ignores them | a mixed graph yields the same ancestors as without workflow edges |
| P5-2 | `workflow.py` `build_workflow` + tests | hybrid trace has the parallel branch and topological order `0,{1,2},3,4,5`; graph trace has no SemanticSearch; details carry real numbers; semantic error and fallback show; JSON round-trips |
| P5-3 | Guarantee tests (3.2) | `build_context` output unchanged with a `_last_workflow` present; no `workflow` id in `node_ids`/`messages`; `Session.messages` untouched |
| P5-4 | Loop recording + fork volatility + tests | graph/hybrid turn writes `_last_workflow`; linear and subagent turns do not; fork drops it |
| P5-5 | `build_tree_graph` `workflow` field + route test | field present with correct anchor after a turn; absent when none; stale record still anchors to its own turn after a later linear turn; existing fields unchanged |
| P5-6 | WebUI: type, toggle, workflow node, layout size, legend, i18n (10 locales) + vitest | toggle shows/hides nodes; build and lint clean |
| P5-7 | Playwright browser check (AGENTS.md *Browser check*): seeded chat, hybrid turn through the temp gateway with mock LLM, toggle on, screenshots, dark mode | screenshots reviewed; temp gateway stopped, 0 sockets |
| P5-8 | Checks: context_graph and touched tests, full `pytest`, `ruff`, `basedpyright` on touched files, `bun run test/build/lint` | green apart from the two known unrelated failures in REVIEW-LATER |
| P5-9 | Docs: `log.md`, MasterGuide (Phase 5 deviations), `docs/REVIEW-LATER.md`, `docs/DEMO-FEATURES.md` | updated |

Files expected to change: new `context_graph/workflow.py`, `tests/context_graph/test_workflow.py`; edited `model.py` (two enum members), `tree.py`, `agent/loop.py` (one line), `session/manager.py` (one set entry), `webui/src/lib/chat-tree.ts`, `ChatMinimap.tsx`, 10 locale files, and the tests that mirror them.

## 5. Risks and honest caveats

- **It is an observability record, not an executor.** The agent does not run *from* this DAG; the nodes describe what the context step did after the fact. The guide allows this ("for now, we can simulate"); we derive instead of simulating, but PromptBuild and LLMCall carry no timing (D4), so those two nodes are placeholders in the picture.
- **Little new information in `graph` mode.** The trace is mostly counts that `/context` and the minimap flags already show; it is clearest in `hybrid` (parallel traversal + search). Say so in the demo.
- **Anchor by position, not id.** If a turn fails before its user message is persisted, the next user message could be shown as the anchor of that trace. Acceptable for a last-turn view; noted in REVIEW-LATER.
- **`GraphTraversal` ms is derived** (`retrieval_ms - embed_ms`), so it includes ranking and rendering time. Labelled "ms" only, not "traversal ms".
- **Strict typing** on the new module (`basedpyright` strict) and the JSON-shaped metadata reads, as in `tree.py`.
- **Machine-translated labels** again in 9 locales; same caveat as the polish pass.
