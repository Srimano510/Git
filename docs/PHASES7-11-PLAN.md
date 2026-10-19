# Phases 7 to 11 plan: from "more complete" to "complete AND selective", plus a demo kit

Status: **Phases 7, 8 and 9 IMPLEMENTED 2026-10-19 (as-built notes in sections 10 to 12); Phases 10 and 11 planned, waiting for approval.**
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

## 10. Phase 7 as built (differences, measurements and findings)

**Built as planned:** `context_graph/embed.py` (`Model2VecEmbedder`, `make_embedder`, `python -m nanobot.context_graph.embed` prefetch), `context_graph/prune.py` (`split_turns`, `prune_by_relevance`), engine integration (`graph_token_budget`, `keep_recent_turns`, relevance reasons, `pruned_by_relevance`, `prune_error`, `graph_budget`, `embedder` diagnostics), config fields, Observatory (`pruned`, `embedder` per strategy, "N pruned by relevance", "Embedder: ..." in 10 locales), `seed_demo.py` with the `noise` scenario and `measure`, `pyproject.toml` optional extra `semantic = ["model2vec>=0.10.0"]`.

**Verified before coding (P7-1):** model2vec 0.10.0 and `minishlab/potion-base-8M` (256 dimensions, about 30 MB, 200 short encodes in 1.6 ms). "car" vs "automobile" 0.78, "car" vs "banana" 0.04; "database for the orders service" vs "we chose Postgres to store orders" 0.54, vs unrelated text 0.10. The hashed embedder scores the first pair 0.

**Differences from the plan**
- **Per-embedder recall cut-off (not planned).** `semanticMinScore` is now unset by default and each embedder carries its own (`hash` 0.15, `model2vec` 0.30). Measured with the real model: unrelated messages score up to 0.21 (noise scenario) and 0.17 (merge scenario), relevant ones from 0.39; with the old 0.15 the dense model let 5 of 28 noise messages (11 of 12 in the merge demo) through and hybrid carried 3 irrelevant recalled messages. An explicit config value still wins.
- **Model files:** `snapshot_download` is limited to the three files a static model needs (`config.json`, `model.safetensors`, `tokenizer.json`); without that the local-only check called the cache "incomplete".
- **Cache location:** `<data dir>/models/hub`. The data dir follows the active config (`~/.nanobot` for the default config), so each instance has its own copy.
- **No env-var override:** the root `conftest.py` already redirects the data dir per test, so tests never see a real model; "auto" falls back to hashed words there.
- **Budget semantics:** `graphTokenBudget` is the *history* budget for graph and hybrid; the recalled block keeps its own cap, so hybrid can exceed it by at most `recallTokenBudget`.

**Pass criteria (fixed before building, section 4.3) and results.** Noise scenario: 16 turns, the two relevant ones first (4 messages), 14 small-talk turns; final question needs both facts. Linear replays all 32 messages (471 tokens).

| | nodes | tokens | relevant | unrelated |
|---|---:|---:|---:|---:|
| linear | 32 | 471 | 4 / 4 | 28 |
| graph, budget 200 | 12 | 190 | 4 / 4 | 8 |
| hybrid, budget 200 | 12 | 190 | 4 / 4 | 8 |

Criteria met: graph and hybrid find at least as many relevant messages as linear, with strictly fewer unrelated messages and fewer tokens (60% fewer tokens, 20 fewer unrelated messages). Enforced by `test_noise_scenario_meets_the_pass_criteria_for_complete_and_selective` (hashed embedder in the test environment) and re-measured with the real model.

**Budget sweep (so the result does not hinge on one number).** Tokens graph / hybrid / linear, relevant found graph / hybrid / linear, unrelated graph / hybrid / linear:

| budget | model2vec tokens | relevant | unrelated | hashed words: relevant |
|---:|---|---|---|---|
| 100 | 97 / 170 / 471 | 2 / 4 / 4 | 4 / 4 / 28 | 2 / 4 / 4 |
| 150 | 132 / 132 / 471 | 4 / 4 / 4 | 4 / 4 / 28 | 4 / 4 / 4 |
| 200 | 190 / 190 / 471 | 4 / 4 / 4 | 8 / 8 / 28 | 4 / 4 / 4 |
| 300 | 299 / 299 / 471 | 4 / 4 / 4 | 16 / 16 / 28 | 4 / 4 / 4 |
| 400 | 379 / 379 / 471 | 4 / 4 / 4 | 22 / 22 / 28 | 4 / 4 / 4 |
| 470 | 444 / 444 / 471 | 4 / 4 / 4 | 26 / 26 / 28 | 4 / 4 / 4 |

The claim holds at every budget from 150 up with both embedders. At 100 tokens, graph alone loses two relevant messages (the budget no longer fits the two protected recent turns plus both relevant turns) and hybrid's recall brings them back. **The demo budget (200) was chosen after this sweep** as about 40% of the full history; the first budget I wrote (350) also met the criteria but with a smaller saving. Below the total, the saving is directly the budget: unrelated messages drop in step with it.

**Browser check (real gateway, mock LLM, real model2vec):** the noise chat's Observatory shows Linear 33 nodes / 489 tokens against Graph and Hybrid 11 nodes / 178 tokens, each with "22 pruned by relevance" and "Embedder: model2vec"; "Differences only" lists the small talk that only linear carries. A real hybrid turn sent 12 messages to the model (system + 10 history + current) against 32+ for linear; the request contained both facts and the newest turns and none of the middle small talk (Mount Elbrus, jazz, pasta, Canberra).

**Findings and fixes along the way**
- **Latent bug (fixed, regression test):** `Config.model_validate(...)` skipped the lazy tool-config resolution that only `__init__` had, so a process that imported `nanobot.context_graph` before `nanobot.config.schema` failed with "Config is not fully defined". `Config` now has the same guard on `model_validate`.
- **`uv sync` side effects:** the first `uv add` could not finish because the owner's running gateway holds `.venv\Scripts\nanobot.exe`; it rolled back cleanly. The extra was added with `uv add --no-sync` and installed with `uv sync --extra semantic --no-install-project --inexact`, which does not touch the running executable. The sync also moved `websockets` from 15.0.1 to 16.1.1, the version the (git-ignored) `uv.lock` pins; the full suite passes with it. `uv.lock` is git-ignored in this repository, so only `pyproject.toml` changes.
- **Types:** `huggingface_hub.snapshot_download` has partly unknown overload types under `basedpyright` strict, so it is reached through `importlib` as `Any`.
- **Caveat on what the demo proves:** turns are split at user messages, so a relevant fact stated mid-turn travels with its whole turn; and the pass criteria are about scripted chats, not every conversation.

## 11. Phase 8 as built (differences and findings)

**Built as planned:** `context_graph/links.py` (`add_link`, `list_links`, `remove_link`, `parse_node`, `MAX_LINKS = 20`), `/context link|links|unlink` in `cmd_context` (keys keep their case; errors are replies, nothing is stored on failure; the `/context` help lists them), the Tree link action, and the single toggle (the header `ContextStrategyBadge` and its props are gone; the composer one stays). The link action reuses `client.sendSystemCommand(chatId, "/context link <id>")`, the same transport as the strategy toggle: no new HTTP route.

**Differences from the plan**
- **Link mode instead of a banner button.** Selecting a Tree node normally *navigates* to that node's chat, which is the opposite of what linking needs. The Tree panel header got a **link mode** button: while on, clicking a message of another branch sends the command to the current chat and stays there. The chat's own history is faded and unclickable (it can only be a no-op or a cycle), linkable messages get blue rings, and the view re-frames to include them. The UI cannot read the command's reply, so after the command it refetches the tree and checks that the new `CONTEXT` edge exists ("Linked ..." or "Could not link (see the chat for the reason)"). The Tree draws `CONTEXT` edges dotted blue.
- **Validation (all with a user-facing message, nothing stored):** unknown chat, message out of range, slash-command messages, a message into itself, duplicates, more than 20 links, and **cycles** (a new edge source -> target closes a cycle exactly when the target is already an ancestor of the source, checked through the source's own graph including its other links).

**Found in the browser and fixed (regression test added)**
- **Default target after other `/context` commands.** The default target was "the latest message", which is a `_command` message whenever the chat ends in command turns (every `/context ...` command leaves two). So `/context link` right after any other context command failed. The default is now the latest non-command message.
- **Silent no-op in link mode** (clicking an already-linked or own-history message did nothing): now visibly disabled.

**Verified (Playwright, temp gateway, real model2vec, mock LLM):** one strategy toggle on screen and none in the header; `/context links` and `/context unlink 1` replies; the Tree link mode (own history faded, branch ringed); "Linked ..." confirmation; the dotted `CONTEXT` edge; and after a *new turn* the branch's messages are in the graph context (`graph: relevance (score 0.68)` with the 200-token budget). A link affects future turns, so the Observatory for the previous turn correctly does not show it.

**Hazard found for the demo (Phase 11):** the gateway **auto-compacts sessions idle for 15 minutes** (`agents.defaults.idleCompactAfterMinutes`, default 15). The seeded demo chats were compacted while I was away, which emptied graph's replay (`0 nodes`) and changed the Observatory's reconstruction. The demo config must set `idleCompactAfterMinutes: 0`, and Phase 9's recorded comparison removes the reconstruction drift for real turns.

## 12. Phase 9 as built (differences and findings)

**Built as planned:** `observatory.compare(snapshot, query, record, load_session, list_sessions, real=None, max_nodes=120)` is now the single code path. `build_observatory` serves `_last_turn["comparison"]` when it belongs to the turn (`comparison.at == _last_turn.at`) and otherwise rebuilds as before. `AgentLoop._turn_history` records the comparison right after the real context is built (`record_comparison`, default `true`), passing the real run (`Real(strategy, history, ms, result)`) so the selected strategy is not recomputed and its numbers are the actual ones; the other two are built from the same pre-turn state. The user message is persisted after `_turn_history`, so the live session already *is* the pre-turn snapshot (no truncation needed). A failure while comparing logs a warning and never touches the turn; subagent turns record nothing; forks drop it with the rest of `_last_turn`. The route needed no change. UI: the label reads "Recorded when the turn was built..." or "Rebuilt from the chat as it was before the last turn..." from `reconstructed`, and a note says how many shared messages the capped list leaves out.

**Differences from the plan**
- **Node cap (planned as "size-bounded", made concrete):** at most `MAX_NODES = 120` listed per comparison. Nodes that differ between strategies are kept first and only shared nodes are dropped; `omitted` says how many; per-strategy counts, tokens and the "only here" totals always cover every node. Needed because linear can replay a whole context window, which would otherwise be rewritten into the session file on every save. The cap applies to rebuilds too.
- **`Real` instead of a result-only parameter:** linear has no `ContextResult`, so a small dataclass carries the strategy name, history, elapsed ms and (for graph/hybrid) the result.

**Verified**
- **Tests:** the Phase 6/7 Observatory tests passed unchanged after the pure refactor (P9-1). New tests (`test_recorded_comparison.py`): the selected strategy's recorded numbers equal the real `ContextResult` (nodes, tokens including the recalled block) for linear, graph and hybrid; flag off records nothing and the route rebuilds; a failure inside `compare` never breaks the turn (warning logged); subagent turns record nothing; **a recorded comparison is identical after the chat is compacted, while a rebuild then shows an empty graph replay**; a stale (`at` mismatch) or garbage recording falls back to a rebuild; the cap keeps differing nodes, keeps counts exact and sorts the list; route test serves a recording as recorded.
- **Browser (temp gateway, real model2vec, mock LLM, idle compaction after 1 minute):** a real hybrid turn recorded Linear 13 nodes / 207 tokens, Graph 15 / 244, Hybrid 17 / 314 (15 history + 2 recalled). The gateway's own log line for that turn read `nodes=15 tokens=244` (history only), agreeing with the recording, and the model request carried the `[Recalled Context]` block. After the gateway auto-compacted the chat the Observatory showed identical numbers and the label "Recorded when the turn was built".
- **A discrepancy that was my seeding, not the recording:** the request held 14 history messages where the engine chose 15, because the seeded demo chat already ended with an unanswered copy of the question and I asked it again live; the provider layer merged the two consecutive user messages. Worth knowing for the demo: do not seed a chat so that it ends in an unanswered user message and then repeat the question.

**Costs and limits (honest)**
- Two extra context builds per turn. In the browser run the gateway logged `ms=1348` for the whole hybrid build on the first turn (model load and embeddings) and the cards show sub-millisecond to low-millisecond figures for the others; with the embedder warm it is a few milliseconds. The flag exists for when that matters.
- The recording stores up to 120 excerpts of 120 characters (about 30 KB at most) in the session file, replaced every turn. Excerpts are the same sanitised public text the route already served.
- Turns recorded before this phase, or with the flag off, still show the rebuilt (drift-prone) comparison, and the label says so.
- Timings of the two strategies that were *not* used are measured at turn time but are not the cost of a real turn.
