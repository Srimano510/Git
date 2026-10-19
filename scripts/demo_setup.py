"""Create a ready-to-run demo instance: a config, an empty workspace and the seeded chats.

    uv run python -m scripts.demo_setup <instance-dir> --provider mock
    uv run python -m scripts.demo_setup <instance-dir> --provider zen --model <zen-model-id>

The instance is separate from your real nanobot (own config, own data, own ports), so the demo
never touches your chats or a gateway you already run. The OpenCode Zen key is referenced as
``${OPENCODE_API_KEY}`` and read from the environment when nanobot loads the config; it is
never written to disk by this script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts import seed_demo

MOCK_PORT = 18999


def build_config(
    instance: Path, *, provider: str, model: str | None, webui_port: int, gateway_port: int, password: str
) -> dict[str, Any]:
    defaults: dict[str, Any] = {"workspace": str(instance / "workspace"), "idleCompactAfterMinutes": 0}
    config: dict[str, Any] = {
        "agents": {"defaults": defaults},
        "channels": {
            "websocket": {"enabled": True, "host": "127.0.0.1", "port": webui_port, "tokenIssueSecret": password}
        },
        "gateway": {"port": gateway_port},
        # idle compaction off: seeded chats must keep their history while you talk
        "contextGraph": {
            "graphTokenBudget": seed_demo.NOISE_BUDGET,
            "semanticEmbedder": "auto",
            "recordComparison": True,
        },
    }
    if provider == "mock":
        defaults.update(provider="openai", model="gpt-4o")
        config["providers"] = {"openai": {"apiKey": "mock", "apiBase": f"http://127.0.0.1:{MOCK_PORT}/v1"}}
    else:
        defaults["modelPreset"] = "primary"
        config["providers"] = {"opencodeZen": {"apiKey": "${OPENCODE_API_KEY}"}}
        config["modelPresets"] = {
            "primary": {
                "provider": "opencode_zen",
                "model": f"opencode/{(model or '').removeprefix('opencode/')}",
                "maxTokens": 8192,
                "contextWindowTokens": 65536,
            }
        }
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("instance", type=Path, help="a new directory for the demo instance")
    parser.add_argument("--provider", choices=("mock", "zen"), required=True)
    parser.add_argument("--model", help="the OpenCode Zen model id (zen only), e.g. one with zero retention")
    parser.add_argument("--webui-port", type=int, default=8775)
    parser.add_argument("--gateway-port", type=int, default=18795)
    parser.add_argument("--password", default="demo", help="the WebUI login password (localhost only)")
    args = parser.parse_args(argv)

    if args.provider == "zen" and not args.model:
        parser.error("--model is required with --provider zen (list models: see demo.md)")
    config_path = args.instance / "config.json"
    if config_path.exists():
        raise SystemExit(f"{config_path} already exists; use a new directory (nothing was changed)")
    args.instance.mkdir(parents=True, exist_ok=True)
    config = build_config(
        args.instance, provider=args.provider, model=args.model,
        webui_port=args.webui_port, gateway_port=args.gateway_port, password=args.password,
    )
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    seed_demo.main([str(args.instance / "workspace"), "--config", str(config_path)])

    mock = "  python -m scripts.mock_llm                      (keep running; the mock LLM)\n" if args.provider == "mock" else ""
    print(
        f"\nDemo instance ready: {args.instance}\n"
        f"WebUI login password: {args.password}   (http://127.0.0.1:{args.webui_port})\n\nNext:\n"
        f"  python -m nanobot.context_graph.embed --config {config_path}   (once: downloads the semantic model)\n{mock}"
        f"  python -m scripts.preflight -c {config_path}\n"
        f"  nanobot gateway -c {config_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
