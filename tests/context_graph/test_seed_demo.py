import pytest

from nanobot.context_graph.observatory import build_observatory
from nanobot.session.manager import SessionManager
from scripts.seed_demo import BRANCH, ROOT, main, report, seed


def included(dto, strategy):
    return {n["id"] for n in dto["nodes"] if n["in"][strategy]}


def test_demo_shows_what_each_strategy_recovers(tmp_path):
    manager = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    relevant = seed(manager)
    dto = build_observatory(ROOT, manager.read_session_snapshot, manager.list_sessions)

    assert dto["selected"] == "hybrid"
    # linear sees neither the archived decision nor the merged branch
    assert included(dto, "linear") & relevant.keys() == set()
    # graph follows the merge edge into the branch, but the archived decision is out of reach
    assert included(dto, "graph") & relevant.keys() == {f"{BRANCH}#4", f"{BRANCH}#5"}
    # hybrid adds the archived Postgres exchange back by similarity
    assert included(dto, "hybrid") >= relevant.keys()
    row = next(n for n in dto["nodes"] if n["id"] == f"{ROOT}#3")
    assert row["reason"]["hybrid"].startswith("vector")

    text = report(manager, relevant)
    assert "hybrid" in text and "4/4" in text and "linear misses:" in text


def test_seed_refuses_to_run_twice_and_needs_a_workspace(tmp_path, capsys):
    ws = tmp_path / "ws"
    assert main([str(ws)]) == 0
    with pytest.raises(SystemExit):
        main([str(ws)])
    with pytest.raises(SystemExit):
        main([])
