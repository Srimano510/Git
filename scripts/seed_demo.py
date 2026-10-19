"""Seed the demo chats: a branch + merge, and a long chat full of small talk.

Usage (the workspace is required; nothing is written anywhere else):

    uv run python -m scripts.seed_demo <workspace> [--scenario merge|noise|both]
                                       [--config config.json] [--report]

Scenarios (see docs/PHASES7-11-PLAN.md):

* ``merge`` (completeness): ``websocket:demo-root`` has the Postgres decision compacted away
  (``last_archived``) and a branch ``websocket:demo-graphs`` merged back by a ``CONTEXT`` edge.
  Linear sees neither; graph sees the branch; hybrid also recalls the archived decision.
* ``noise`` (selectivity): ``websocket:demo-noise`` is one long chat. Two early turns hold the
  facts the last question needs; everything else is small talk. Linear replays all of it;
  graph and hybrid keep the facts and the latest turns under a small token budget.

``--report`` prints, per strategy, how many relevant messages each put in the context, how many
unrelated ones came along, and the tokens.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from nanobot.config.schema import ContextGraphConfig
from nanobot.context_graph.observatory import build_observatory
from nanobot.session.manager import SessionManager

ROOT = "websocket:demo-root"
BRANCH = "websocket:demo-graphs"
NOISE = "websocket:demo-noise"
QUESTION = "Which database holds the orders service, and how do graphs and vectors complement each other?"
NOISE_QUESTION = "Which database holds the orders service, and where do we deploy it?"
# History tokens for graph/hybrid in the noise scenario (config: graphTokenBudget). About 40% of the
# full history (471 tokens); chosen after a sweep (docs/PHASES7-11-PLAN.md): 4/4 relevant from 150 up.
NOISE_BUDGET = 200

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

NOISE_FACTS = [
    ("user", "We chose Postgres for the orders database because it handles transactions well."),
    ("assistant", "Noted: the orders service stores its data in Postgres."),
    ("user", "The deploy target for the orders service is Fly.io, in the Frankfurt region."),
    ("assistant", "Understood: we deploy the orders service to Fly.io in Frankfurt."),
]
NOISE_TALK = [
    ("Any tips for a long flight?", "Drink water, walk the aisle now and then, and bring a good book."),
    ("What is the tallest mountain in Europe?", "Mount Elbrus in Russia reaches about 5,642 metres."),
    ("Suggest a pasta recipe.", "Try aglio e olio: garlic, olive oil, chili flakes and parsley over spaghetti."),
    ("Why is the sky blue?", "Air scatters short blue wavelengths of sunlight more than long red ones."),
    ("Who painted the Mona Lisa?", "Leonardo da Vinci painted it in the early sixteenth century."),
    ("How do I stretch my back?", "Try a gentle cat-cow stretch on all fours, breathing slowly."),
    ("Recommend a jazz album.", "Kind of Blue by Miles Davis is the classic starting point."),
    ("How many moons does Mars have?", "Two small ones, Phobos and Deimos."),
    ("What should I plant in spring?", "Peas, lettuce and radishes enjoy the cool early weather."),
    ("Explain offside in football.", "A player is offside when nearer the goal than the ball and the last defender."),
    ("Best way to learn guitar?", "Practise a little every day and learn songs you love."),
    ("What is the capital of Australia?", "Canberra, not Sydney or Melbourne."),
    ("How long to boil an egg?", "About seven minutes for a soft yolk, ten for hard-boiled."),
    ("Name a good board game.", "Carcassonne is easy to learn and plays in half an hour."),
]


def _fork(manager: SessionManager) -> Any:
    branch = manager.fork_session_before_user_index(ROOT, BRANCH, 2)
    if branch is None:
        raise SystemExit(f"could not fork {BRANCH} from {ROOT}")
    return branch


def _fresh(manager: SessionManager, key: str) -> Any:
    session = manager.get_or_create(key)
    if session.messages:
        raise SystemExit(f"{key} already has messages; use an empty workspace")
    return session


def seed(manager: SessionManager) -> dict[str, str]:
    """The merge scenario; returns the node ids that are relevant to the demo question."""
    root = _fresh(manager, ROOT)
    for role, text in PROJECT:
        root.add_message(role, text)
    manager.save(root)

    branch = _fork(manager)
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


def seed_noise(manager: SessionManager) -> dict[str, str]:
    """The noise scenario; returns the node ids that are relevant to the final question."""
    chat = _fresh(manager, NOISE)
    for role, text in NOISE_FACTS:
        chat.add_message(role, text)
    for ask, answer in NOISE_TALK:
        chat.add_message("user", ask)
        chat.add_message("assistant", answer)
    chat.metadata["context_strategy"] = "hybrid"
    chat.metadata["_last_turn"] = {
        "strategy": "hybrid",
        "at": len(chat.messages),
        "max_tokens": 100_000,
        "graph_config": ContextGraphConfig(graph_token_budget=NOISE_BUDGET).model_dump(),
    }
    chat.add_message("user", NOISE_QUESTION)
    manager.save(chat)
    return {
        f"{NOISE}#0": "Postgres decision",
        f"{NOISE}#1": "Postgres answer",
        f"{NOISE}#2": "Fly.io decision",
        f"{NOISE}#3": "Fly.io answer",
    }


def measure(manager: SessionManager, key: str, relevant: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Per strategy: nodes, tokens, ms, relevant found, unrelated ('noise') and pruned counts."""
    dto = build_observatory(key, manager.read_session_snapshot, manager.list_sessions)
    assert dto is not None
    out: dict[str, dict[str, Any]] = {}
    for name in ("linear", "graph", "hybrid"):
        info = dto["strategies"][name]
        got = {n["id"] for n in dto["nodes"] if n["in"][name]}
        hit = got & relevant.keys()
        out[name] = {
            "nodes": info["nodes"], "tokens": info["tokens"], "ms": info["ms"],
            "relevant": len(hit), "noise": len(got) - len(hit), "pruned": info.get("pruned", 0),
            "embedder": info.get("embedder"), "missed": sorted(relevant[i] for i in relevant.keys() - hit),
        }
    out["_query"] = {"text": dto["query"]}
    return out


def report(manager: SessionManager, relevant: dict[str, str], key: str = ROOT) -> str:
    m = measure(manager, key, relevant)
    lines = [f"[{key}] Question: {m.pop('_query')['text']}", f"Relevant: {len(relevant)} messages", ""]
    lines.append(f"{'strategy':<8} {'nodes':>5} {'tokens':>6} {'ms':>6} {'relevant':>9} {'noise':>6} {'pruned':>6}")
    for name, v in m.items():
        lines.append(
            f"{name:<8} {v['nodes']:>5} {v['tokens']:>6} {v['ms']:>6} "
            f"{v['relevant']:>4}/{len(relevant):<4} {v['noise']:>6} {v['pruned']:>6}"
        )
    lines.append("")
    for name, v in m.items():
        lines.append(f"{name} misses: {', '.join(v['missed']) or 'nothing'}")
    embedders = {v["embedder"] for v in m.values() if v["embedder"]}
    lines.append(f"embedder: {', '.join(sorted(embedders)) or 'n/a'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("workspace", type=Path, help="workspace to seed (use a scratch one)")
    parser.add_argument("--scenario", choices=("merge", "noise", "both"), default="both")
    parser.add_argument("--config", type=Path, help="config.json the gateway uses (WebUI transcripts)")
    parser.add_argument("--report", action="store_true", help="print the per-strategy comparison")
    args = parser.parse_args(argv)

    if args.config:
        from nanobot.config.loader import set_config_path

        set_config_path(args.config)
    manager = SessionManager(args.workspace)
    seeded: list[tuple[str, dict[str, str]]] = []
    if args.scenario in ("merge", "both"):
        seeded.append((ROOT, seed(manager)))
    if args.scenario in ("noise", "both"):
        seeded.append((NOISE, seed_noise(manager)))
    keys = [ROOT, BRANCH] * (args.scenario in ("merge", "both")) + [NOISE] * (args.scenario in ("noise", "both"))
    if args.config:
        from nanobot.webui.transcript import write_session_messages_as_transcript

        for key in keys:
            if (saved := manager.read_session_snapshot(key)) is not None:
                write_session_messages_as_transcript(key, saved.messages)
    print(f"seeded {', '.join(keys)} in {args.workspace}")
    if args.report:
        for key, relevant in seeded:
            print()
            print(report(manager, relevant, key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
