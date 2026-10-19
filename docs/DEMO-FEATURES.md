# Demo features: what this project adds to nanobot

Everything below is new compared with upstream nanobot. The project goal ([AGENTS.md](../AGENTS.md)): show a different way of building LLM context. Instead of replaying one flat transcript, the agent can build its prompt from a **typed-edge DAG of the conversation** (branches, replies, links), optionally topped up with **semantic recall** and **summaries**. One toggle switches between the old and the new way, so the same question can be answered both ways and compared.

Per-phase plans and decisions: [PHASE3-PLAN.md](PHASE3-PLAN.md), [PHASE3_5-PLAN.md](PHASE3_5-PLAN.md), [PHASE4-PLAN.md](PHASE4-PLAN.md), [PHASE5-PLAN.md](PHASE5-PLAN.md), [PHASE6-PLAN.md](PHASE6-PLAN.md). Demo walk-through: [DEMO-SCENARIO.md](DEMO-SCENARIO.md). Open questions: [REVIEW-LATER.md](REVIEW-LATER.md). Status log: [../log.md](../log.md).

## 1. The three context strategies

| Strategy | What the model sees | Switch with |
|---|---|---|
| `linear` (default, baseline) | The session history, as upstream nanobot does it. | `/context linear`, or the toggle |
| `graph` | History gathered by walking the conversation DAG: reaches back through forks into the source chats (even where a fork's copy was trimmed or compacted), never into sibling branches. | `/context graph`, or the toggle |
| `hybrid` | `graph`, plus a labelled "[Recalled Context]" block in the system prompt with earlier messages similar to the current message and any summaries standing in for dropped ranges. | `/context hybrid`, or the toggle |

The toggle appears twice (chat header and composer); both share one state and the choice is saved per chat and survives reload.

## 2. Features, by phase

### Phase 1: strategy toggle
- `ContextStrategyBadge` (header and composer) and `/context` command; `ContextResult` records what each build used (node ids, reasons, token count, timing, diagnostics).
- Code: `nanobot/context_graph/observability.py`, `nanobot/command/builtin.py`, `webui/src/components/thread/ContextStrategyBadge.tsx`.

### Phase 2: branching
- Fork a chat from any message (copies the history up to that point into a new chat). The message menu (three dots, "More actions") holds **Fork**; **Copy** stays visible.
- Code: `SessionManager.fork_session_before_user_index`, `nanobot/webui/forking.py`.

### Phase 3: the typed-edge DAG
- Nodes are addresses `(chat, message number)`, so no message is copied. Edges are typed: `REPLY` (message order), `BRANCH` (fork point), `CONTEXT` (extra link, read from chat metadata), plus `REFERENCE`/`SUMMARY` types reserved.
- The resolver collects every ancestor reachable through the typed edges, parents first, tolerating cycles and diamonds. The engine applies the token budget and falls back to linear history on any failure.
- Code: `nanobot/context_graph/model.py`, `resolver.py`, `derive.py`, `engines.py`.

### Phase 3.5: the chat tree
- **Tree** button opens a panel with the whole chat family (the root chat and all its forks) as a pan/zoom map.
- Mouse wheel pans, Shift+wheel pans sideways, Ctrl+wheel zooms. Detail follows zoom: dots, one line, full text.
- Long linear runs fold into "+N messages"; click one to expand. The active path is highlighted, other branches dimmed.
- Optional small overview map (map icon in the panel header), expand/shrink button, works in dark mode and narrow windows.
- **Click a node** to open that chat at that point. Pick an earlier node and **send a message**: a "Branching from..." banner appears, and sending forks the chat there first, then delivers the message in the new chat. From a user message it pre-fills the composer (re-ask).
- Slash-command turns (`/context ...`) are hidden from the tree.
- Code: `nanobot/context_graph/tree.py` (`GET /api/sessions/{key}/graph`), `webui/src/components/thread/ChatMinimap.tsx`, `webui/src/lib/chat-tree.ts`.

### Phase 4: hybrid retrieval and summaries
- **Semantic recall:** a dependency-free hashed bag-of-words embedder scores earlier messages against the current message. Matches shared words, not meaning (swappable behind an `Embedder` interface).
- **Pools:** `archived` (this chat's own earlier messages that are no longer replayed) or `family` (also sibling branches). Config default plus per-chat override.
- **Summaries:** `/context summary <from> <to> <text>` stores a manual summary of a message range; it replaces those messages in the recalled block only when they are not replayed. Works on forks (prefix ranges map to the source chat).
- **Budgets:** the recalled block has its own token cap, reserved out of the history budget.
- **What the tree shows after a turn:** "vector" and "summary" badges on recalled nodes, an "in context" label on folded runs, and a legend.
- Config (`~/.nanobot/config.json`): `contextGraph.semanticPool`, `semanticTopK`, `semanticMinScore`, `recallTokenBudget` (see [configuration.md](configuration.md#context-graph-experimental)).
- Code: `nanobot/context_graph/embed.py`, `recall.py`, `summaries.py`, `engines.py`.

### Phase 5: workflow DAG
- After every `graph` or `hybrid` turn the chat records a small **workflow DAG** of the steps that built its context: strategy selection, graph traversal and semantic search (in parallel, `TRIGGERS` edges), context merge, prompt build, LLM call (`FEEDS` edges). Each step shows real numbers from that turn (nodes visited and pruned, search hits, token count, ms for the steps that are timed).
- In the **Tree** panel, the **Workflow** button (flow icon in the panel header, only when a trace exists) draws these steps in violet under the user message of that turn. Last turn only; off by default.
- The steps are an observability record, never chat messages: they are not stored in the transcript, and the context engine never follows their edge types, so they cannot reach the prompt.
- Code: `nanobot/context_graph/workflow.py`, `tree.py` (`workflow` field of `GET /api/sessions/{key}/graph`), `ChatMinimap.tsx`.

### Phase 6: Context Observatory
- The **Context** button (bottom right of a chat) opens a drawer that compares what `linear`, `graph` and `hybrid` would put in the context for the chat's **last turn**: one card per strategy (nodes, tokens, ms, "used for this turn", fallback if one failed), a timing breakdown (traversal, vector, total), and a node table with a mark per strategy, the reason each node was included, and a "Differences only" filter.
- It is **rebuilt on demand** from the chat as it was before that turn (`GET /api/sessions/{key}/context-result`), so it never changes the answer and costs nothing per turn. It is a reconstruction: compaction since the turn can make it differ from what the model received. Timings are of the rebuild.
- The loop logs one line per turn for every strategy: `Context strategy=<s> nodes=<n> tokens=<t> ms=<x>` (plus `recall=<hits>` for hybrid).
- Demo data: `scripts/seed_demo.py` builds a branch plus a merge link and prints a per-strategy report; see [DEMO-SCENARIO.md](DEMO-SCENARIO.md).
- Code: `nanobot/context_graph/observatory.py`, `ws_http.py` (route), `webui/src/components/thread/ContextObservatory.tsx`, `agent/loop.py` (`_turn_history`).

## 3. Commands

| Command | Effect |
|---|---|
| `/context` | Show strategy, pool and summary count |
| `/context linear\|graph\|hybrid` | Switch strategy for this chat |
| `/context hybrid archived\|family\|default` | Switch to hybrid and set or clear the recall pool for this chat |
| `/context summary <from> <to> <text>` | Add a summary of messages from..to (numbers shown in the tree) |
| `/context summary` / `/context summary clear` | List / clear summaries |

## 4. A five-minute demo script

1. Start the WebUI (`nanobot webui`). Open a chat, talk about a topic with a clear fact ("we picked Postgres for the orders service"), then 6 to 8 unrelated turns.
2. Open **Tree**: one long chain. Fork from an early message, continue differently, and watch the two branches appear. Pick an earlier node and send from it to branch visually.
3. Switch the chat to `graph` and ask something in the fork: the model sees its own ancestry, not the sibling's answers.
4. For `hybrid`: make the old fact fall out of the replayed history (long chat, or compaction), switch to `hybrid`, and ask "which database did we choose for orders?". Open the tree: the old messages carry a "vector" badge; the model request contains the "[Recalled Context]" block.
5. Press **Context** to compare linear, graph and hybrid for the last turn; tick **Differences only** to see what each strategy uniquely adds. (A ready-made branch + merge chat: [DEMO-SCENARIO.md](DEMO-SCENARIO.md).)
6. After any `graph`/`hybrid` turn, open **Tree** and press the **Workflow** button to see how that turn's context was built (graph traversal and semantic search side by side, then merge, prompt, LLM call).
7. Add `/context summary 0 7 Early on we chose Postgres.`, shrink the budget, and see the summary used instead of the raw range ("summary" badge).

## 5. How it was verified

- Unit and integration tests under `tests/context_graph/`, `tests/command/test_context_command.py`, `tests/config/`, and the WebUI tests (`webui/src/tests/chat-tree.test.ts`, `chat-minimap.test.tsx`, `thread-shell.test.tsx`).
- Browser checks with Playwright against an isolated test gateway (see *Browser check* in [AGENTS.md](../AGENTS.md)). End to end, a mock LLM's request log showed the recalled block reaching the model while the replayed history no longer contained the archived messages.

## 6. Known limits (honest list)

- The embedder matches shared words only; it will not connect "car" and "automobile".
- `graph` and `linear` look alike in short, unforked chats; the difference shows with forks, compaction and `hybrid`.
- The `family` pool breaks branch isolation by design (opt-in).
- The Observatory is a reconstruction from the pre-turn state with rebuild timings, not a recording of what the model received; in the scripted demo graph and hybrid are more complete than linear but not smaller (no noise reduction).
- The workflow DAG is a record made after the context step, not something the agent runs from. It keeps the last turn only, and `PromptBuild` and `LLMCall` have no duration (no timing was added to the agent loop).
- Not implemented yet: split windows, `/context link`.
