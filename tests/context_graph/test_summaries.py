import pytest

from nanobot.context_graph.summaries import (
    SUMMARIES_KEY,
    add_summary,
    clear_summaries,
    list_summaries,
    usable_summaries,
)
from nanobot.session import Session


def session(n=6, key="s"):
    s = Session(key=key)
    for i in range(n):
        s.add_message("user" if i % 2 == 0 else "assistant", f"m{i}")
    return s


def test_add_list_clear_roundtrip():
    s = session()
    add_summary(s, 0, 3, "  early discussion  ")
    assert list_summaries(s) == [{"from": 0, "to": 3, "text": "early discussion"}]
    assert s.metadata[SUMMARIES_KEY] == list_summaries(s)
    assert clear_summaries(s) == 1
    assert list_summaries(s) == []
    assert SUMMARIES_KEY not in s.metadata


@pytest.mark.parametrize("args", [(-1, 2, "x"), (3, 2, "x"), (0, 6, "x"), (0, 2, "   ")])
def test_invalid_ranges_or_text_are_rejected(args):
    with pytest.raises(ValueError):
        add_summary(session(), *args)


def test_list_tolerates_garbage_metadata():
    s = session()
    s.metadata[SUMMARIES_KEY] = ["x", {"from": "a"}, {"from": 0, "to": 1, "text": "ok"}, None]
    assert list_summaries(s) == [{"from": 0, "to": 1, "text": "ok"}]


def test_used_only_when_every_covered_ancestry_node_was_dropped():
    s = session()
    add_summary(s, 0, 3, "early")
    ancestry = [("s", i) for i in range(6)]
    # whole range dropped -> used
    out = usable_summaries({"s": s}, ancestry, kept={("s", 4), ("s", 5)})
    assert [(u.key, u.start, u.end, u.text) for u in out] == [("s", 0, 3, "early")]
    # one covered node still replayed -> raw wins, summary skipped
    assert usable_summaries({"s": s}, ancestry, kept={("s", 3), ("s", 4), ("s", 5)}) == []
    # range outside ancestry (e.g. aliased fork prefix owned elsewhere) -> ignored
    assert usable_summaries({"s": s}, [("other", 0)], kept=set()) == []


def fork_family(tmp_path):
    from nanobot.session.manager import SessionManager

    m = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    src = m.get_or_create("websocket:src")
    for i in range(8):
        src.add_message("user" if i % 2 == 0 else "assistant", f"s{i}")
    add_summary(src, 0, 1, "source summary")
    m.save(src)
    kid = m.fork_session_before_user_index(src.key, "websocket:kid", 2)  # copies s0..s3
    for i in range(4):
        kid.add_message("user" if i % 2 == 0 else "assistant", f"k{i}")
    m.save(kid)
    return m, src, kid


def test_summary_over_a_forks_copied_prefix_maps_to_the_source_nodes(tmp_path):
    m, src, kid = fork_family(tmp_path)
    add_summary(kid, 2, 3, "prefix summary written on the fork")
    sessions = {"websocket:src": src, "websocket:kid": kid}
    ancestry = [("websocket:src", i) for i in range(4)] + [("websocket:kid", i) for i in range(4, 8)]

    out = usable_summaries(sessions, ancestry, kept={("websocket:kid", i) for i in range(4, 8)})

    assert {u.text: u.head for u in out} == {
        "source summary": ("websocket:src", 0),
        "prefix summary written on the fork": ("websocket:src", 2),
    }


def test_inherited_copy_of_a_summary_is_not_counted_twice(tmp_path):
    m, src, kid = fork_family(tmp_path)  # kid inherited src's "source summary" with the metadata copy
    assert list_summaries(kid) == list_summaries(src)
    sessions = {"websocket:src": src, "websocket:kid": kid}
    ancestry = [("websocket:src", i) for i in range(4)] + [("websocket:kid", i) for i in range(4, 8)]

    out = usable_summaries(sessions, ancestry, kept={("websocket:kid", i) for i in range(4, 8)})
    assert [u.text for u in out] == ["source summary"]
