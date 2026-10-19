"""Read-only checks to run before a live demo.

    uv run python -m scripts.preflight -c <config.json> [--live]

Prints one PASS / WARN / FAIL line per check and exits 1 if anything failed. It never prints
the API key. Nothing is written or downloaded; `--live` makes one tiny model call.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from nanobot.config.errors import ConfigLoadError
from nanobot.config.loader import load_config, resolve_config_env_vars, set_config_path
from nanobot.config.schema import Config
from nanobot.context_graph.embed import make_embedder
from nanobot.session.manager import SessionManager

Status = Literal["PASS", "WARN", "FAIL"]
DEMO_CHATS = ("websocket:demo-root", "websocket:demo-graphs", "websocket:demo-noise")


@dataclass(frozen=True)
class Check:
    status: Status
    name: str
    detail: str


def _is_local(base: str | None) -> bool:
    return bool(base) and urlparse(base or "").hostname in {"127.0.0.1", "localhost"}


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def check_provider(config: Config) -> list[Check]:
    try:
        preset = config.resolve_preset()
    except KeyError as exc:
        return [Check("FAIL", "provider", f"model preset not found: {exc}")]
    name = config.get_provider_name(preset=preset) or "no provider"
    base = config.get_api_base(preset=preset)
    label = f"{name} / {preset.model}"
    if _is_local(base):
        try:
            urllib.request.urlopen(f"{(base or '').rstrip('/')}/models", timeout=2).read()
        except OSError:
            return [Check("FAIL", "provider", f"{label} points at {base} but nothing answers; start it with `python -m scripts.mock_llm`")]
        return [Check("PASS", "provider", f"{label} -> mock LLM at {base}")]
    key = config.get_api_key(preset=preset) or ""
    if not key or key.startswith("${"):  # an unresolved ${VAR} reference is not a key
        hint = f" ({key[2:-1]} is not set)" if key.startswith("${") and key.endswith("}") else ""
        return [Check("FAIL", "provider", f"{label}: no API key found{hint}; put it in the config or its environment variable")]
    return [Check("PASS", "provider", f"{label} (API key set, not shown)")]


def check_live(config: Config) -> list[Check]:
    """One tiny real call through the configured provider."""
    from nanobot.providers.factory import make_provider

    preset = config.resolve_preset()
    key = config.get_api_key(preset=preset) or ""

    async def ask() -> str:
        provider = make_provider(config)
        reply = await provider.chat_with_retry(
            [{"role": "user", "content": "Reply with the single word OK."}],
            tools=None, model=preset.model, max_tokens=16,
        )
        if reply.finish_reason == "error":
            raise RuntimeError(reply.content or "provider error")
        return reply.content or ""

    started = time.perf_counter()
    try:
        asyncio.run(ask())
    except Exception as exc:
        message = str(exc).replace(key, "***") if key else str(exc)
        return [Check("FAIL", "live model call", f"{type(exc).__name__}: {message[:200]}")]
    return [Check("PASS", "live model call", f"answered in {(time.perf_counter() - started) * 1000:.0f} ms")]


def check_embedder(config: Config) -> Check:
    cg = config.context_graph
    if cg.semantic_embedder == "hash":
        return Check("PASS", "embedder", "hashed words (configured); matches shared words only")
    # never download from a preflight: probe what a turn would use ("auto" = installed and cached)
    embedder = make_embedder(cg.model_copy(update={"semantic_embedder": "auto"}))
    if getattr(embedder, "name", "") == "model2vec":
        return Check("PASS", "embedder", f"model2vec ({cg.semantic_model}), semantic matching")
    return Check(
        "WARN", "embedder",
        "hashed words will run: the semantic model is not installed or not downloaded. "
        "Run `uv sync --extra semantic` then `python -m nanobot.context_graph.embed`",
    )


def check_webui(dist: Path) -> Check:
    if (dist / "index.html").exists():
        return Check("PASS", "WebUI build", str(dist))
    return Check("FAIL", "WebUI build", f"no build at {dist}; run `cd webui && bun run build`")


def check_ports(config: Config, in_use: Callable[[str, int], bool] = _port_in_use) -> list[Check]:
    ws = getattr(config.channels, "websocket", None)
    if not isinstance(ws, dict) or not ws.get("enabled", False):  # type: ignore[reportUnknownMemberType]
        return [Check("FAIL", "WebUI channel", "`channels.websocket.enabled` is not true, so the WebUI cannot be served")]
    host, port = str(ws.get("host", "127.0.0.1")), int(ws.get("port", 8765))  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    out: list[Check] = []
    for label, h, p in (("WebUI", host, port), ("gateway", "127.0.0.1", config.gateway.port)):
        busy = in_use(h, p)
        out.append(Check(
            "WARN" if busy else "PASS", f"port {p} ({label})",
            "in use: the demo is already running, or another program holds it" if busy else "free",
        ))
    return out


def check_demo_config(config: Config) -> list[Check]:
    idle = config.agents.defaults.session_ttl_minutes
    cg = config.context_graph
    return [
        Check("PASS", "idle compaction", "off") if idle == 0 else Check(
            "WARN", "idle compaction",
            f"idle chats are compacted after {idle} minutes, which empties the seeded chats' history; "
            "set `agents.defaults.idleCompactAfterMinutes` to 0",
        ),
        Check("PASS", "graph token budget", f"{cg.graph_token_budget} tokens") if cg.graph_token_budget > 0 else Check(
            "WARN", "graph token budget",
            "0 means no pruning; the noise demo needs `contextGraph.graphTokenBudget` (200 in the scenario)",
        ),
        Check("PASS", "recorded comparison", "on") if cg.record_comparison else Check(
            "WARN", "recorded comparison",
            "off: the Observatory will rebuild comparisons, which can drift after compaction",
        ),
    ]


def check_chats(manager: SessionManager) -> list[Check]:
    missing = [k.split(":", 1)[1] for k in DEMO_CHATS if manager.read_session_snapshot(k) is None]
    if missing:
        return [Check(
            "WARN", "demo chats",
            f"not seeded: {', '.join(missing)}. Seed them: `python -m scripts.seed_demo <workspace> --config <config.json>`",
        )]
    return [Check("PASS", "demo chats", "demo-root, demo-graphs, demo-noise are present")]


def run_checks(
    config: Config,
    *,
    manager: SessionManager,
    dist: Path,
    port_in_use: Callable[[str, int], bool] = _port_in_use,
    live: bool = False,
) -> list[Check]:
    checks = check_provider(config)
    if live and checks[0].status != "FAIL":
        checks += check_live(config)
    checks += [check_embedder(config), check_webui(dist)]
    checks += check_ports(config, port_in_use)
    checks += check_demo_config(config)
    checks += check_chats(manager)
    return checks


def main(argv: list[str] | None = None) -> int:
    import nanobot

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-c", "--config", type=Path, required=True, help="the demo instance's config.json")
    parser.add_argument("--live", action="store_true", help="also make one tiny call through the configured model")
    parser.add_argument("--dist", type=Path, default=Path(nanobot.__file__).parent / "web" / "dist")
    args = parser.parse_args(argv)

    set_config_path(args.config)
    config = load_config(args.config)
    early: list[Check] = []
    try:
        config = resolve_config_env_vars(config, config_path=args.config)
    except ConfigLoadError as exc:  # names the missing variables, never a value
        early.append(Check("FAIL", "environment", "; ".join(i.message for i in exc.issues) or exc.summary))
    checks = early + run_checks(
        config, manager=SessionManager(config.workspace_path), dist=args.dist, live=args.live
    )
    for c in checks:
        print(f"{c.status:<4}  {c.name}: {c.detail}")
    counts = {s: sum(c.status == s for c in checks) for s in ("PASS", "WARN", "FAIL")}
    print(f"\n{counts['PASS']} passed, {counts['WARN']} warnings, {counts['FAIL']} failed")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
