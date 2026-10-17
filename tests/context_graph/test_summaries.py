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
