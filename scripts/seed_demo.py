"""Seed the Phase 6 demo: a root chat, a branch, a merge link and one recorded turn.

Usage (the workspace is required; nothing is written anywhere else):

    uv run python -m scripts.seed_demo <workspace> [--config config.json] [--report]

Chats created (see docs/DEMO-SCENARIO.md):

* ``websocket:demo-root``   project talk, then unrelated chatter; the Postgres decision has
  been compacted away (``last_archived``); the last message is the question of the demo turn.
* ``websocket:demo-graphs`` a branch forked after the Postgres decision: "graphs vs vectors".
* a ``CONTEXT`` edge in the root chat's metadata is the merge: the branch's answer feeds the root.

``--report`` prints, per strategy, how many of the known-relevant messages each one put in
the context, and how many other messages came along (noise).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nanobot.config.schema import ContextGraphConfig
from nanobot.context_graph.observatory import build_observatory
from nanobot.session.manager import SessionManager

ROOT = "websocket:demo-root"
BRANCH = "websocket:demo-graphs"
QUESTION = "Which database holds the orders service, and how do graphs and vectors complement each other?"

PROJECT = [
    ("user", "I'm building an AI agent for customer support."),
    ("assistant", "Great. Decide early how it stores conversations and which tools it can call."),
    ("user", "We chose Postgres for the orders database."),
    ("assistant", "Noted: the orders service uses Postgres, which handles transactions well."),
]
BRANCH_TALK = [
    ("user", "What about graphs vs vectors for the agent's memory?"),
    (
        "assistant",
        "Graph and vector synergy: typed edges give structure, vectors give fuzzy recall of old facts.",
    ),
]
CHATTER = [
    ("user", f"Tell me a fun fact about topic number {i}")
    if role == "user"
    else ("assistant", f"Fun fact {i}: bananas are berries and tomatoes are fruit.")
    for i in range(6)
    for role in ("user", "assistant")
]


def seed(manager: SessionManager) -> dict[str, str]:
    """Create the demo chats; returns the node ids that are relevant to the demo question."""
    if manager.get_or_create(ROOT).messages:
        raise SystemExit(f"{ROOT} already has messages; use an empty workspace")
    root = manager.get_or_create(ROOT)
    for role, text in PROJECT:
        root.add_message(role, text)
    manager.save(root)

    branch = manager.fork_session_before_user_index(ROOT, BRANCH, 2)
    if branch is None:
        raise SystemExit(f"could not fork {BRANCH} from {ROOT}")
    for role, text in BRANCH_TALK:
        branch.add_message(role, text)
    manager.save(branch)

    for role, text in CHATTER:
        root.add_message(role, text)
    root.last_archived = len(PROJECT)  # the project talk is compacted out of the replay
    tip = len(root.messages) - 1
    root.metadata["context_edges"] = [{"source": [BRANCH, 5], "target": [ROOT, tip]}]  # the merge
    root.metadata["context_strategy"] = "hybrid"
    root.metadata["_last_turn"] = {
        "strategy": "hybrid",
        "at": len(root.messages),
        "max_tokens": 100_000,
        "graph_config": ContextGraphConfig().model_dump(),
    }
    root.add_message("user", QUESTION)
    manager.save(root)
    return {
        f"{ROOT}#2": "Postgres decision (archived)",
        f"{ROOT}#3": "Postgres answer (archived)",
        f"{BRANCH}#4": "branch question",
        f"{BRANCH}#5": "branch answer (merged in)",
    }


def report(manager: SessionManager, relevant: dict[str, str]) -> str:
    dto = build_observatory(ROOT, manager.read_session_snapshot, manager.list_sessions)
    assert dto is not None
    lines = [f"Question: {dto['query']}", f"Relevant: {len(relevant)} messages", ""]
    lines.append(f"{'strategy':<8} {'nodes':>5} {'tokens':>6} {'ms':>6} {'relevant':>9} {'noise':>6}")
    for name in ("linear", "graph", "hybrid"):
        info = dto["strategies"][name]
        got = {n["id"] for n in dto["nodes"] if n["in"][name]}
        hit = len(got & relevant.keys())
        lines.append(
            f"{name:<8} {info['nodes']:>5} {info['tokens']:>6} {info['ms']:>6} "
            f"{hit:>4}/{len(relevant):<4} {len(got) - hit:>6}"
        )
    missed = {
        name: sorted(
            relevant[i]
            for i in relevant
            if not any(n["id"] == i and n["in"][name] for n in dto["nodes"])
        )
        for name in ("linear", "graph", "hybrid")
    }
    lines.append("")
    for name, what in missed.items():
        lines.append(f"{name} misses: {', '.join(what) or 'nothing'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("workspace", type=Path, help="workspace to seed (use a scratch one)")
    parser.add_argument("--config", type=Path, help="config.json the gateway uses (WebUI transcripts)")
    parser.add_argument("--report", action="store_true", help="print the per-strategy comparison")
    args = parser.parse_args(argv)

    if args.config:
        from nanobot.config.loader import set_config_path

        set_config_path(args.config)
    manager = SessionManager(args.workspace)
    relevant = seed(manager)
    if args.config:
        from nanobot.webui.transcript import write_session_messages_as_transcript

        for key in (ROOT, BRANCH):
            if (saved := manager.read_session_snapshot(key)) is not None:
                write_session_messages_as_transcript(key, saved.messages)
    print(f"seeded {ROOT} and {BRANCH} in {args.workspace}")
    if args.report:
        print(report(manager, relevant))
    return 0


if __name__ == "__main__":
    sys.exit(main())
