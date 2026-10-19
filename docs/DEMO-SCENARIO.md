# Demo scenario: branch, merge and the Context Observatory

A repeatable chat family that makes the three strategies (`linear`, `graph`, `hybrid`) answer the same question with visibly different context. Feature overview: [DEMO-FEATURES.md](DEMO-FEATURES.md). Plan: [PHASE6-PLAN.md](PHASE6-PLAN.md).

## 1. Set it up

Use a scratch workspace and the config your test gateway uses (never your real one):

```bash
uv run python -m scripts.seed_demo <scratch-workspace> --config <test-config.json> --report
nanobot gateway -c <test-config.json> -p <spare-port>
```

The script refuses to run without a workspace path and refuses a workspace that already holds the demo. It creates:

| Chat | Content |
|---|---|
| `websocket:demo-root` | "I'm building an AI agent..." then **"We chose Postgres for the orders database"** (messages 0-3, compacted away: `last_archived = 4`), then six unrelated "fun fact" exchanges. Last message: *"Which database holds the orders service, and how do graphs and vectors complement each other?"* |
| `websocket:demo-graphs` | A **branch** forked after the Postgres decision: *"What about graphs vs vectors for the agent's memory?"* and the answer **"Graph and vector synergy: typed edges give structure, vectors give fuzzy recall of old facts."** |
| merge | A `CONTEXT` edge in the root chat's metadata from the branch's answer to the root's last message ("merge at graph and vector synergy"). |

The root chat has one recorded turn, so its Observatory works without calling a model. Both chats show the same first message as their title; the root is the one with the fun facts.

## 2. Walk through (Act 1, 2, 3)

1. **Act 1, the problem.** Open the root chat, press **Tree**: root chain, a branch hanging off message 3, and the merge. The question needs two facts that a flat transcript does not hold: the archived Postgres decision and the branch's answer.
2. **Act 2, three contexts.** Press **Context** (Observatory). Three cards show nodes, tokens and ms per strategy; "used for this turn" marks the selected one. Tick **Differences only**:
   - `demo-graphs#4`, `#5` (the branch): marked **G** and **H**, reason `context` (the merge edge). Linear cannot see another chat.
   - `demo-root#2`, `#3` (the Postgres exchange): marked **H** only, reason `vector (score 0.41)`. Graph skips them because they were compacted out; recall brings them back.
3. **Act 3, switch and ask.** Toggle the chat between `linear`, `graph`, `hybrid` (header toggle or `/context graph`), ask the question for real, and reopen **Context**: the "used for this turn" mark moves and the Observatory now describes your own turn.

## 3. What the numbers say (from `--report`)

Relevant messages for the question: the Postgres exchange (2) and the branch exchange (2).

| Strategy | Nodes | Tokens | Relevant found | Other messages |
|---|---:|---:|---:|---:|
| linear | 12 | 186 | 0 / 4 | 12 |
| graph | 14 | 223 | 2 / 4 | 12 |
| hybrid | 17 | 317 | 4 / 4 | 13 |

- **Linear** misses everything relevant: the branch lives in another chat and the Postgres exchange is archived.
- **Graph** follows the merge edge and recovers the branch (2 of 4), but not the archived decision.
- **Hybrid** adds the archived decision back by similarity (4 of 4) at the cost of 42% more tokens than graph here.
- **Honest reading:** the graph and hybrid contexts are *more complete*, not smaller. In this scenario all three strategies carry the same 12 unrelated fun-fact messages (the "other messages" column), so none of them reduces noise. A noise reduction would need a chat where unrelated messages can be pruned by the budget or sit in a sibling branch. Timings are of the rebuild and are not a speed benchmark (see the plan's risks).
- The similarity scores come from a hashed bag-of-words embedder, which matches shared words ("orders", "database", "Postgres"), not meaning.

## 4. Slide outline

1. **Problem.** A conversation is a graph (branches, merges, side questions), but chat history is a flat list. Show the root chat's Tree next to its linear transcript.
2. **Limits of linear history.** Missing context (other branches, compacted facts) and stale/irrelevant context (chatter that always comes along). The 0 / 4 row.
3. **Graph representation.** Nodes are addresses into the session store; typed edges `REPLY`, `BRANCH`, `CONTEXT` (and the workflow edges `TRIGGERS`, `FEEDS`); the resolver collects ancestors through those edges. Tree screenshot.
4. **Context engine architecture.** Derive the DAG per turn, resolve ancestors, budget and legality through the existing replay code, optional recall block, fallback to linear on any failure. Phases 3 to 5 in one diagram.
5. **Phase progression.** Toggle and observability (1), branching (2), typed-edge DAG (3), chat tree (3.5), hybrid recall and summaries (4), workflow trace (5), Observatory (6).
6. **Demo comparison.** Observatory screenshots with "Differences only" on: the merged branch (graph, hybrid) and the archived fact (hybrid only).
7. **Performance metrics.** The table in section 3, plus the log line the loop writes for every turn (`Context strategy=... nodes=... tokens=... ms=...`). State plainly that hybrid costs more tokens and that timings are rebuild timings.
8. **Conclusion.** Graph-based context is structured and explainable: every node comes with a reason. It is not automatically smaller. Future work: real embeddings, LLM-written summaries, a `/context link` command, recording all strategies at turn time, side-by-side panes.

## 5. Reset

The demo chats are ordinary chats in the scratch workspace; delete the workspace (or the two sessions) to start over.
