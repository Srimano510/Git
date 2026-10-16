# AGENTS.md

Guidance for AI coding agents working in **nanobot**, a lightweight, open-source AI agent framework in Python with a React/TypeScript WebUI. It centers on a small agent loop that receives messages from chat channels, invokes an LLM provider, executes tools, and manages session memory.

## Context & Status Tracking (required)

Before doing anything, read `log.md` up to the latest Change log record to get the current context and task status. While working, use `log.md` as your todo list: add tasks as `[ ]`, mark `[~]` when you start, `[x]` when done (or `[!]` with notes if it fails), and log every change to files in this repository so later agents can diagnose and resume after a mid-run failure.

**`archive/` (skip by default):** old CI and error logs live here. Don't read, search or list it unless the current task needs a past failure (a recurring or similar error, or a regression). Token saving is key.

**`nanobot/docs/` (skip by default):** don't read these docs unless the task needs the information in them.

## Project reference
* read the MasterGuide-vN.md at the root to get the context of the project

## Workflow for any change (agents)

1. **Orient** as in *Context & Status Tracking*, plus the `.agent/*.md` files and the code the change touches. Work on a branch, not on `main`.
2. **Decide.** If the change alters a goal, an architecture constraint, a security boundary or a public contract (see *Working rules*), say so and get the owner's agreement first. Record the decision in the matching `.agent/*.md` file before writing code.
3. **Plan** the tasks in `log.md`. Split anything bigger than one sitting into steps that each have a "done when" check.
4. **Build test-first, in small steps.** Write the failing test, then the code. Tests mirror the `nanobot/` package structure. Keep logic in the agent, provider, channel and tool layers where unit tests reach it, not in CLI glue or WebUI components.
5. **Check.** Run the narrowest checks first, then the full ones (commands in *Development commands*):
   - `pytest` for the touched tests, then the full suite.
   - `ruff check nanobot/`.
   - `basedpyright` (strict, matches CI) after any typing-relevant change.
   - `cd webui && bun run test` and `bun run build` after any WebUI change.
6. **Review** the diff before committing, and fix what the review finds.
7. **Document** as in *End of Run Behavior*: `log.md`, the matching `.agent/*.md` file, the README or config docs if user-visible behaviour changed, and the *Parts to keep in mind* row you touched.
8. **Review Later:** record any decision the owner should revisit in `docs/REVIEW-LATER.md` (create it if missing).
9. **Commit** only as *Git & Commits* allows (owner permission for each commit).
10. **Finish** as in *End of Run Behavior*.

## Development commands

```bash
# Python: run single test / lint
pytest tests/test_openai_api.py::test_function -v
ruff check nanobot/

# Strict type checking (matches CI)
uv sync --all-extras --dev
uv run --no-sync python -m scripts.install_channel_dependencies --all-channels
uv run --no-sync basedpyright

# WebUI: dev server (proxies API/WS to gateway :8765), build, test
# Build outputs to ../nanobot/web/dist (bundled into the Python wheel)
cd webui && bun run dev      # or NANOBOT_API_URL=... bun run dev
cd webui && bun run build
cd webui && bun run test

# Gateway
nanobot gateway
```

## High-level architecture

### Core data flow

Messages flow through an async `MessageBus` (`nanobot/bus/queue.py`) that decouples chat channels from the agent core:

1. **Channels** (`nanobot/channels/`) receive messages from external platforms and publish `InboundMessage` events to the bus.
2. **`AgentLoop`** (`nanobot/agent/loop.py`) consumes inbound messages, builds context, and coordinates the turn.
3. **`AgentRunner`** (`nanobot/agent/runner.py`) handles the LLM conversation loop: send messages to the provider, receive tool calls, execute tools, and stream responses.
4. Responses are published as `OutboundMessage` events back to the appropriate channel.

### Key subsystems

- **Agent Loop** (`nanobot/agent/loop.py`, `runner.py`): the core processing engine. `AgentLoop` manages session keys, hooks and context building. `AgentRunner` executes the multi-turn LLM conversation with tool execution.
- **LLM Providers** (`nanobot/providers/`): Anthropic, OpenAI-compatible, OpenAI Responses API, Azure, Bedrock, GitHub Copilot, OpenAI Codex and others, built on a common base (`base.py`). Includes image generation (`image_generation.py`) and audio transcription (`transcription.py`). `factory.py` and `registry.py` handle instantiation and model discovery.
- **Channels** (`nanobot/channels/`): Telegram, Discord, Slack, Feishu, Matrix, WhatsApp, QQ, WeChat, WeCom, DingTalk, Email, MoChat, MS Teams, WebSocket, Mattermost. `manager.py` discovers and coordinates them. Channels are self-contained packages auto-discovered via `pkgutil` scanning.
- **Tools** (`nanobot/agent/tools/`): filesystem (read/write/edit/list), shell execution (with sandbox backends), web search/fetch, MCP servers, cron, notebook editing, subagent spawning, long-running tasks / sustained goals (`long_task.py`), image generation, and self-modification. Auto-discovered via `pkgutil` scan plus entry-point plugins.
- **Memory** (`nanobot/agent/memory.py`): session history persistence with Dream two-phase memory consolidation. Uses atomic writes with fsync for durability.
- **Session Management** (`nanobot/session/`): per-session history, context compaction, TTL-based auto-compaction (`manager.py`), and sustained goal state tracking (`goal_state.py`).
- **Config** (`nanobot/config/schema.py`, `loader.py`): Pydantic-based configuration loaded from `~/.nanobot/config.json`. Supports camelCase aliases for JSON compatibility.
- **WebUI** (`webui/`): Vite-based React SPA that talks to the gateway over a WebSocket multiplex protocol. The dev server proxies `/api`, `/webui`, `/auth` and WebSocket traffic to the gateway.
- **API Server** (`nanobot/api/server.py`): OpenAI-compatible HTTP API (`/v1/chat/completions`, `/v1/models`) for programmatic access.
- **Command Router** (`nanobot/command/`): slash command routing and built-in command handlers.
- **Heartbeat** (`nanobot/templates/HEARTBEAT.md`): periodic task list checked via `cron` jobs (the legacy dedicated service was removed).
- **Pairing** (`nanobot/pairing/`): DM sender approval store with persistent pairing codes per channel.
- **Skills** (`nanobot/skills/`): built-in skill definitions (cron, github, image-generation, etc.) loaded into agent context.
- **Security** (`nanobot/security/`): PTH file guard and other protections activated at CLI entry.

### Entry points

- **CLI**: `nanobot/cli/commands.py`
- **Python SDK**: `nanobot/nanobot.py`

## Parts to keep in mind

| Part | Where | When you change it, also … |
|---|---|---|
| Message bus and agent core | `nanobot/bus/`, `nanobot/agent/loop.py`, `runner.py` | every channel and the API server depend on it; run the full `pytest`; keep `InboundMessage`/`OutboundMessage` fields additive |
| Providers | `nanobot/providers/` | follow `base.py`; register in `registry.py`/`factory.py`; add a provider test and a config schema entry; keep strict typing clean |
| Channels | `nanobot/channels/` | follow `channels/base.py`; stay self-contained so `pkgutil` discovery works; add its dependency to the channel installer script; DM approval goes through `pairing/` |
| Tools | `nanobot/agent/tools/` | register via the tool registry (`registry.py`) or an entry point; check `.agent/security.md` for shell/filesystem boundaries; add tests |
| Memory and sessions | `nanobot/agent/memory.py`, `nanobot/session/` | keep atomic write plus fsync; stored session data is a contract, so add fields only and migrate old data |
| Config | `nanobot/config/schema.py`, `loader.py` | new fields need defaults and camelCase aliases so old `config.json` files still load; update docs and tests |
| WebUI | `webui/` | build output goes to `nanobot/web/dist`; keep `vite.config.ts` proxy in step with gateway routes; run `bun run test` and `bun run build` |
| API server | `nanobot/api/server.py` | keep OpenAI compatibility; add or update tests (`tests/test_openai_api.py`) |
| Security | `nanobot/security/`, `.agent/security.md` | any change to shell, filesystem, network or pairing behaviour must be reflected in `.agent/security.md` and tested |
| Skills and templates | `nanobot/skills/`, `nanobot/templates/` | these load into agent context, so keep them short and re-test the affected behaviour |
| Dependencies | `pyproject.toml`, `uv.lock`, `webui/package.json`, lockfile | use `uv` and `bun` locally; see *Dependencies (strict)* |
| Tests | `tests/`, `webui` tests | mirror the `nanobot/` structure; the full suite passes before a commit |
| Docs | `log.md`, `.agent/*.md`, `README.md`, `docs/REVIEW-LATER.md`, `CONTRIBUTING.md` | update the doc that states the old behaviour, plus `log.md` |

## Working rules

- **If a goal, constraint or requirement changes, reflect it in every document it affects:** the matching `.agent/*.md` file first, then README, config defaults, `log.md` and anything else that states the old behaviour.
- Published contracts only grow. Never rename or remove fields in the config schema, `InboundMessage`/`OutboundMessage`, the OpenAI-compatible API responses, the WebUI WebSocket protocol, or stored session/memory data that another component reads. Add a new field or version instead.
- Respect the security boundaries in `.agent/security.md`. Don't weaken sandboxing, path guards or pairing checks to make a task easier; raise it with the owner instead.
- Python 3.11+, asyncio throughout. Line length 100. `ruff` rules E, F, I, N, W (E501 ignored). `pytest` runs with `asyncio_mode = "auto"`.
- Tunable values (timeouts, limits, TTLs, URLs) go in the config schema with defaults, not hard-coded.
- Build in small, testable steps. After a change to the agent loop, runner or session handling, run the related tests before moving on.
- Add appropriate tests for what you build or change. Fix bugs with a regression test.

## Common file locations

- Config schema: `nanobot/config/schema.py`
- Provider base / new provider template: `nanobot/providers/base.py`
- Channel base / new channel template: `nanobot/channels/base.py`
- Tool registry: `nanobot/agent/tools/registry.py`
- WebUI dev proxy config: `webui/vite.config.ts`
- Tests mirror the `nanobot/` package structure.

## Dependencies (strict)

Keep every dependency install local to the project: Python packages through `uv` (project environment, `uv sync`), JavaScript packages through `bun` inside `webui/` (no global installs), and tools run with `uv run` or `bunx`. Never install anything globally (system packages, `npm -g`, a global Python, Node or Bun on the machine, global PATH or registry changes) unless it is absolutely necessary, and then only after asking the user and getting explicit permission. Log any approved global install in `log.md`.

## Git & Commits

- **Prompt to commit before and after each piece of work.** Before starting a substantial task, and again when it is finished, ask the user whether to commit the current state. Commit only with their explicit permission, for that commit only (one approval doesn't cover the next). Don't push unless they ask for that too. If they decline, record it in `log.md` and carry on.
- Follow the commit and PR conventions in `CONTRIBUTING.md`. If it has none, use `<type>: <summary>` (for example `feat:`, `fix:`, `docs:`, `chore:`).
- Check the diff for stray build outputs (`nanobot/web/dist`, caches, `node_modules`, virtual environments) before staging.

## Mid-run behavior

- Do not leave any download or dependency artifact unhandled.
- Go through `.gitignore` after every install and update, and change it if necessary.
- No dependency folder or build output shall be tracked or pushed, unless absolutely necessary.

## Working with the owner

- Feel free to ask about any critical decision mid-run.
- If you find bugs mid-run, fix them (with a test) and log them in `log.md`.
- If you've made 7 attempts at the same step without a passing check, stop. Report what you tried, what failed and the options you see, and wait for direction. (Skipped only when the owner says to run without supervision.)

## End of run behavior

At the end of the run, before the finishing summary, make sure of the following:

- All running instances (gateway, WebUI dev server, test watchers) are terminated, unless explicitly requested to keep one running.
- 0 background tasks and 0 open sockets remain.
- The docs related to the current task or bug are reviewed and updated to reflect the changes and fixes made, and `log.md` has its final entry.
