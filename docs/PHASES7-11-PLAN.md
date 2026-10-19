# Phases 7 to 11 plan: from "more complete" to "complete AND selective", plus a demo kit

Status: **PLANNED 2026-10-19, decisions recorded, waiting for owner approval to implement.** No code changed.
Branch for planning: `phase7`. Each phase gets its own branch (`phase7` ... `phase11`) and its own commit(s) by the owner. Governing rule ([AGENTS.md](../AGENTS.md)): minimum code, reuse the existing structure; the typed-edge DAG stays the only new core idea. Everything below either *proves* the claim, *removes a known gap*, or *makes the demo safe*.

## 1. Project goals (owner answers, 2026-10-19)

| Question | Answer |
|---|---|
| How is it judged? | **Live demo + slides.** The demo path must be repeatable and must survive a bad network or model. |
| Headline claim | **Complete AND selective:** graph/hybrid recover context that linear misses (branches, archived facts) **and** drop irrelevant noise at smaller or equal token cost. |
| Effort | **Several phases, quality first**, each planned, built, tested and committed separately. |
| LLM in the demo | A **free OpenCode Zen model** so far. Zen documents chat, responses and messages endpoints but **no embeddings endpoint**, so any real embedder must be local. Free models are "free for a limited time", so a fallback is needed. Some free models have zero retention and no training (GLM-5.3-Flash Free, DeepSeek V4.1 Flash Free, Space Bunny Free, LongCat 2.5 Preview Free); others may use data for model improvement. Chats go to the provider, so the demo uses a zero-retention one. |
| Extra | A root **`demo.md`** listing everything added (from `log.md`), why, how it helps, plus the commands and setup for the demo. |

### Where the project stands against the claim
Measured in Phase 6 (`docs/DEMO-SCENARIO.md`): linear 0/4 relevant found, graph 2/4, hybrid 4/4, but **the same 12 unrelated messages in all three, and 42% more tokens for hybrid than graph**. So "complete" is shown; **"selective" is not**: graph replays the whole ancestry after the archive pointer, exactly like linear. Phases 7 to 11 close that gap and the gaps that would hurt a live demo.

## 2. Decisions (owner answers, 2026-10-19)

| # | Decision | Outcome |
|---|---|---|
| D1 | Embedder | **model2vec as an optional extra** (`semantic`), local, numpy only, no torch. The hashed embedder stays as the automatic fallback when the extra or the model is not available. |
| D2 | Selectivity | **Relevance-pruned replay under a dedicated graph token budget.** Summary substitution is not a separate mechanism, but it comes for free (see 3.2). |
| D3 | LLM summaries | **On demand: `/context summarize <from> <to>`**, using the configured model; stored like manual summaries and labelled generated. |
| D4 | Observatory exactness | **Record the other strategies at turn time behind a config flag**; reconstruction remains the fallback. |
| D5 | Toggles | **Keep the composer toggle**, remove the header one. |
| D6 | `/context link` | **Command plus a Tree UI action** (and list/unlink). |
| D7 | `demo.md` | **One root `demo.md`** replacing `docs/DEMO-FEATURES.md` and `docs/DEMO-SCENARIO.md` (folded in, files removed, links fixed). |
| D8 | Demo safety | **Mock-LLM fallback plus a preflight script**; the real run uses a zero-retention free Zen model. |

## 3. Roadmap

| Phase | Theme | Why it matters for the claim | Size |
|---|---|---|---|
| **7** | Selective context: real embedder, graph token budget, relevance pruning, noise demo data | Proves "selective"; also turns the hashed matcher into real semantic matching | largest |
| **8** | Linking and UI cleanup: `/context link\|links\|unlink`, Tree "Link into this chat", single toggle | Lets the demo create the merge live; removes a redundant control | medium |
| **9** | Exact Observatory: record all three strategies at turn time | Removes the "it's a reconstruction" caveat from the headline numbers | small-medium |
| **10** | LLM summaries: `/context summarize` | Smaller context with the meaning kept; completes the summary story | medium |
| **11** | Demo kit: mock LLM, preflight, seed scenarios, `demo.md`, slide outline, rehearsal | A repeatable, safe live demo and the documentation you asked for | medium |

Order is by value to the claim and by dependency: 7 before 10 (summaries replace pruned ranges), 9 before 11 (exact numbers in the demo), 11 last (documents everything).

### Facts found in the code that shape the plan (read-only audit, P7-0)
- `GraphContextEngine.build_context` already receives `query` for graph and hybrid; `replayable` is the ancestry after each owner's `last_archived` with command turns excluded (Phase 6 fix). It budgets only by handing `max_tokens` to `Session.get_history`, which keeps the **newest** messages that fit, so today's graph "selection" is recency, not relevance.
- `AgentLoop._graph_context` passes `max_tokens=context_window_tokens` (the whole window) to the graph engine. A dedicated budget is therefore a new config field plus using it there and in `_last_turn`.
- `embed.py` defines the `Embedder` protocol (`embed(text) -> dict[int, float]`, normalised); `cosine` works on any such sparse/dense dict. A dense model fits by returning `{index: value}`; no protocol change.
- `recall.py` already excludes tool/hidden/command/empty messages and takes `top_k` and `min_score`; relevance pruning reuses that visibility filter.
- `usable_summaries` uses a summary when **every covered node was dropped from the replay**, so once pruning drops a range, a stored summary (manual or generated) automatically stands in for it in the recalled block.
- `cmd_context` (`command/builtin.py`) is an `async` handler with `ctx.loop`, `ctx.session`, `ctx.runtime`; `loop.context.memory.summarize_transcript(...)` is the existing async summarizer (needs a runtime, a session key and tool schemas). It parses `raw_args` itself (lowercasing caveat noted in Phase 4).
- The strategy toggle already persists through `/context <strategy>` sent over the normal chat transport; the Tree's "Branching from" banner (`ThreadShell`, `handleSelectTreeNode`, `branchFrom`) is the place for a second action. No new HTTP mutation route is needed.
- `ContextStrategyBadge` is used in `ThreadHeader.tsx` and `ThreadComposer.tsx`; `ThreadShell` owns the shared state.
- `_last_turn` already stores `max_tokens` and `graph_config`, so new config fields reach the Observatory rebuild automatically.
- The Phase 6 scratch mock LLM (`mockllm.py`) and `seed_demo.py` are the starting points for the demo kit.
- Dependencies: `pyproject.toml` has no embedding library; a new extra needs `uv add --optional semantic model2vec` (local, per AGENTS.md) and a `uv.lock` change. A model download lands in a Hugging Face cache; see the caveat in section 5.

## 4. Phase 7: selective context (largest phase)

### 4.1 Real embedder (D1)
- `embed.py`: `Model2VecEmbedder` (lazy import of `model2vec`, model name from config, per-text LRU cache so a turn embeds each message once); `make_embedder(config)` returns it when the extra and the model are available, else `HashEmbedder`, logging which one is active once.
- Config (`ContextGraphConfig`, all with defaults and camelCase aliases): `semantic_embedder` (`auto` | `hash` | `model2vec`, default `auto`), `semantic_model` (default a small static model such as `minishlab/potion-base-8M`; exact id verified in P7-1).
- The model download is directed into the nanobot runtime data dir (not the global user cache) so nothing is left unmanaged; documented in `demo.md`.
- `diagnostics["embedder"]` records which embedder ran; the Observatory shows it.
- `semantic_min_score` default stays; a dense model scores differently from hashed words, so the defaults are re-checked against the demo data in P7-6 and changed only if the demo needs it.

### 4.2 Graph budget and relevance pruning (D2)
- Config: `graph_token_budget` (default `0` = unchanged behaviour: the whole context window), `keep_recent_turns` (default 2).
- Engine, when `graph_token_budget > 0` and the replay exceeds it:
  1. Split the replay into **turns** (a user message plus everything up to the next user message), so tool-call/result pairs are never separated.
  2. Always keep the last `keep_recent_turns` turns.
  3. Score older turns by cosine similarity of their text to the query, tie-break by recency; keep the best until the budget is reached; restore chronological order.
  4. Reasons: kept older turns get `relevance (score 0.41)`; dropped turns are counted (`diagnostics["pruned_by_relevance"]`) and, in hybrid, remain eligible for recall like any other node outside the replay.
- Below the budget nothing changes, so existing chats and tests are unaffected.
- Linear is untouched and keeps replaying everything up to the context window: that is the honest baseline.
- The loop passes `graph_token_budget` through `_last_turn.graph_config`, so Observatory rebuilds use the same rules.

### 4.3 Noise demo data
- `seed_demo.py` gets a second scenario (`--scenario noise`, the existing one stays as `merge`): a long chat where two older turns hold the facts the final question needs and many turns are unrelated (the guide's "irrelevant or stale info"), with a budget chosen so graph prunes and linear does not.
- `--report` prints, per strategy: nodes, tokens, relevant found, noise count. **Pass criteria, written before building:** graph and hybrid find at least as many relevant messages as linear, with strictly fewer noise messages and fewer or equal tokens than linear. If the numbers do not show that, the claim is reported as not met (not tuned until it looks good without saying so).

### 4.4 Observatory touches
Card shows the embedder name and "N pruned by relevance"; reasons column shows `relevance (score ...)`. i18n for the new strings in 10 locales.

### Tasks (mirrored in [log.md](../log.md)); test-first, each with a done-when
| ID | Task | Done when |
|---|---|---|
| P7-0 | Audit (read-only) | section 3 facts, recorded in `log.md` |
| P7-1 | `uv add --optional semantic model2vec` (local); verify the exact model id and API by a small throwaway script in the scratchpad; decide cache location | extra installs with `uv sync --extra semantic`; model loads offline after one download; findings in `log.md` |
| P7-2 | `Model2VecEmbedder`, `make_embedder`, config fields + tests | related words score above unrelated ones ("car" vs "automobile" test, skipped when the extra is missing); missing extra falls back to hashed with one log line; cache avoids re-embedding; old config files load |
| P7-3 | Turn splitter + relevance pruning in the engine + tests (fake embedder, no model needed) | under budget: output identical to today; over budget: last turns kept, relevant old turn kept, noisy old turns dropped, tool pairs intact, order chronological, budget respected; hybrid recall can still bring a dropped turn back; summaries stand in for a pruned range |
| P7-4 | Loop: use `graph_token_budget`; `_last_turn` carries it + tests | graph/hybrid turn builds with the dedicated budget; linear unchanged |
| P7-5 | Observatory: embedder name, pruned count, reasons + vitest, i18n | shown and tested |
| P7-6 | Noise scenario in `seed_demo.py` + report + test of the pass criteria; tune budget and thresholds only through config, and record the numbers | criteria in 4.3 met, or reported as not met |
| P7-7 | Playwright check on a temp gateway with the noise chat (both embedders if the model is available) | screenshots reviewed; servers stopped, 0 sockets |
| P7-8 | Checks: full pytest, ruff, basedpyright, `bun run test/build/lint` | green apart from known unrelated failures |
| P7-9 | Docs: log, MasterGuide (Phase 7 deviations), REVIEW-LATER (closes "smaller graph budget", "embedder quality"), `docs/configuration.md` | updated |

## 5. Phase 8: linking and UI cleanup

### 8.1 `/context link`, `links`, `unlink` (D6)
- Pure module `context_graph/links.py`: `add_link(session, source, target, load_session)`, `list_links(session)`, `remove_link(session, n)`; data stays in `session.metadata["context_edges"]` (existing format, read by `derive.py`).
- Syntax: `/context link <chat-key>#<n> [<m>]`: edge from that message into message `<m>` of the current chat (default: the current tip). Validation: source session and index exist; target index exists; **no cycle** (reject when the target is an ancestor of the source); no duplicates; a sane cap on edges per chat. Errors return a usage line, nothing is stored.
- `/context links` lists edges with a preview of both ends; `/context unlink <n>` removes one. The `/context` help text lists them.
- Chat keys are long, so typing them is for tests and power use; the UI action below is the normal way.

### 8.2 Tree UI action
- When a Tree node is selected, the banner offers **Link into this chat** next to the branch action; it sends `/context link <key>#<n>` through the same transport the strategy toggle uses (serialised with turns, no new HTTP route). New CONTEXT edge shows in the tree after the refetch. Disabled for nodes already in the current chat's ancestry. i18n in 10 locales.

### 8.3 One toggle (D5)
- Remove `ContextStrategyBadge` from `ThreadHeader.tsx` and its props/wiring in `ThreadShell`; keep the composer one. Update the tests that assert two toggles; the sync test becomes "toggle persists after reload".

### Tasks
| ID | Task | Done when |
|---|---|---|
| P8-0 | Audit: where the banner, transport and header toggle wiring live | findings in `log.md` |
| P8-1 | `links.py` + tests | add/list/remove; bad key, bad index, self-link, cycle, duplicate, cap all rejected with a message and no change; a link makes graph include the source branch (the Phase 6 demo, now live) |
| P8-2 | `/context link\|links\|unlink` in `cmd_context` + tests (also covers `/context` argument lowercasing: keys keep their case) | command round-trip through `CommandRouter` |
| P8-3 | Tree banner action + vitest + i18n | click node -> Link -> command sent -> tree refetch shows the edge |
| P8-4 | Remove the header toggle + tests updated | one toggle; persistence after reload still tested |
| P8-5 | Playwright: link from the Tree, confirm graph context changes in the Observatory; dark mode and narrow width | screenshots reviewed |
| P8-6 | Checks and docs | as P7-8/P7-9; REVIEW-LATER entries for toggle and `/context link` closed |

## 6. Phase 9: exact Observatory (D4)

- Config `record_comparison` (default **true**, per the owner's "default on for the demo"; one-line flip to false in config). When on, `_turn_history` builds the **other two** strategies from the pre-turn snapshot right after the real one (diagnostic only, never sent to the model), using the **real** result for the selected strategy so its numbers are the actual ones, and stores the sanitized comparison DTO in `_last_turn["comparison"]`.
- `build_observatory` is split into `compare(snapshot, query, record, selected_result)` (used by both the loop and the route) so there is one code path.
- Route: if a recorded comparison exists, return it with `reconstructed: false`; else rebuild as today. UI label and tooltip change between "Recorded at the time of the turn" and "Rebuilt from ..."; timings of the selected strategy are then the real turn's.
- Safety: wrapped in try/except (a comparison failure never affects the turn), size-bounded (excerpts already truncated; node cap), fork-volatile already (`_last_turn`).
- Cost: measured and logged (`ms`) in the metrics line; the flag exists because a real embedder makes three builds per turn more than free.

| ID | Task | Done when |
|---|---|---|
| P9-0 | Audit the loop path and session size impact | findings logged |
| P9-1 | Refactor `build_observatory` into `compare` + tests unchanged (pure refactor first) | Phase 6 tests pass unchanged |
| P9-2 | Config flag + recording in `_turn_history` + tests | on: comparison stored, selected strategy numbers equal the real `ContextResult`; off: nothing stored; failure inside the comparison never breaks the turn; subagent turns skip; forks drop it |
| P9-3 | Route and UI use the recorded comparison, label change + vitest + i18n | recorded vs rebuilt both tested; the earlier compaction-after-turn caveat test shows recorded stays exact |
| P9-4 | Playwright + full checks + docs | as before |

## 7. Phase 10: LLM summaries (D3)

- `/context summarize <from> <to>`: validates the range like `/context summary`, builds the covered messages (public form, no runtime context), calls `loop.context.memory.summarize_transcript` with the session's runtime, and stores the text via the existing summaries store with an additive `source: "llm"` field; a failure or empty result stores nothing and replies with the reason. Range size is capped; the existing summary token cap applies.
- Reasons show `summary (generated, covers a-b)`; manual ones stay `summary (covers a-b)`.
- Works with Phase 7: once the budget prunes the covered range, the summary stands in for it in the recalled block (hybrid), which is the "smaller context, meaning kept" demo.
- Not doing: automatic generation on compaction (kept as a REVIEW-LATER item).

| ID | Task | Done when |
|---|---|---|
| P10-0 | Audit: summarizer inputs, runtime access from a command, token caps | findings logged |
| P10-1 | `summaries.py`: `source` field, add helper + tests | old records still load; new field additive |
| P10-2 | `/context summarize` handler + tests with a fake summarizer (success, failure, empty, bad range, cap) | nothing stored on failure; stored text labelled generated |
| P10-3 | Engine reason label + Observatory text + i18n + vitest | shown |
| P10-4 | Playwright with the mock LLM (summary path) + checks + docs | screenshots; green suite |

## 8. Phase 11: demo kit

- `scripts/mock_llm.py`: the scratch mock promoted, deterministic OpenAI-compatible (streaming and not), canned answers keyed on the demo questions, logs requests to a file so the recalled block can be shown reaching the model.
- `scripts/preflight.py`: read-only checks with PASS/FAIL lines: config loads (no secrets printed), provider key present, `--live` makes one tiny model call, embedder available (`model2vec` loaded or hashed fallback named), WebUI build present, ports free, demo chats seeded, record flag on, nothing running on the demo ports.
- `seed_demo.py`: both scenarios, idempotent refusal, `--config` for WebUI transcripts, and a one-line report block that `demo.md` quotes.
- **`demo.md`** (root, D7): (1) what the project is and the claim; (2) **everything added**, phase by phase (sourced from `log.md`), each with *what*, *why*, *how it helps the claim*, *where in code*; (3) setup: `uv sync --extra semantic`, `bun` build, config snippet for the **OpenCode Zen** provider (key via env, a zero-retention free model; the model list command `curl .../inference/v1/models` rather than hard-coded ids that may change), mock-LLM switch; (4) the exact commands (seed, gateway, preflight, mock, WebUI) for Windows PowerShell and bash; (5) the demo script (Acts 1-3 plus the noise act) with expected observations and the measured numbers table; (6) honest limits; (7) troubleshooting. `docs/DEMO-FEATURES.md` and `docs/DEMO-SCENARIO.md` are folded in and removed; links in plans, README and `log.md` updated.
- Slide outline moves into `demo.md` (final section), with the claim table and screenshots taken from the rehearsal.
- Rehearsal: I run the full script with Playwright on a temp gateway with the mock LLM and capture the screenshots; the owner runs it once with the real Zen model.

Things I suggest adding to demonstrate the goal best (all inside the tasks above, none extra scope):
1. A **claim table** printed by `seed_demo --report` for both scenarios, so the slide numbers come from a command, not a screenshot.
2. A **token meter in the Observatory cards** (already there: tokens + bar) with the **graph budget** shown, so "smaller" is visible next to "complete".
3. The **mock fallback** and the **preflight**, because a live demo fails on the network first.
4. A **zero-retention model** recommendation, because the chats include your project text.

| ID | Task | Done when |
|---|---|---|
| P11-0 | Audit: ports, config keys, WebUI build path, Windows shell differences | findings logged |
| P11-1 | `mock_llm.py` + test | answers canned and deterministic; streaming works; request log written |
| P11-2 | `preflight.py` + tests (fake config, fake ports) | each check passes/fails as designed; no secret printed |
| P11-3 | `seed_demo.py` final (both scenarios) + tests | pass criteria from 4.3 enforced by a test |
| P11-4 | Playwright rehearsal of the whole script on the mock | screenshots reviewed; temp servers stopped |
| P11-5 | Write `demo.md`; remove the two docs/ files; fix links | every command in it was run once; no dangling links |
| P11-6 | Final checks, docs, `log.md` | green |

## 9. Risks and honest caveats

- **The claim might not be met.** Relevance pruning drops tokens, but a dropped turn can be one the question needed (the embedder is a heuristic). The pass criteria are fixed first (4.3), and if they fail the plan reports it rather than tuning silently.
- **model2vec downloads a model on first use** (needs network once). Cache location is directed into the runtime data dir, not the global Hugging Face cache; if the download fails, the hashed fallback runs and the Observatory shows it. I will verify the exact package API and model id in P7-1 before writing code against them (they are from memory, not checked).
- **A new dependency** touches `pyproject.toml` and `uv.lock`; it is an optional extra, installed locally with `uv`, and logged in `log.md` per AGENTS.md. Nothing is installed globally.
- **Behaviour change in graph mode** only when `graph_token_budget > 0`. Default `0` keeps today's results, so existing chats and tests are unaffected; the demo config sets the budget.
- **Phase 9 adds per-turn work** (two more builds, embeddings). Default on per the owner's wording; if a live demo ever feels slow it is one config line to turn off.
- **`/context link` writes session metadata** through the chat transport, so it is serialised with turns; a link added while a turn is running is applied after it.
- **LLM summaries cost a model call** and may be wrong; they are labelled generated and never replace the raw messages.
- **The free Zen period can end** and free models rotate; `demo.md` names how to list current models and falls back to the mock. Model ids in this plan are not hard-coded.
- **Machine-translated labels** keep growing in 9 locales; same caveat as before.
- **Scope honesty for the slides:** even after Phase 7, the claim is about the scripted demo chats, not about every real conversation.
