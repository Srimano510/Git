import pytest

from nanobot.context_graph import GraphContextEngine
from nanobot.context_graph.links import (
    MAX_LINKS,
    add_link,
    list_links,
    parse_node,
    remove_link,
)
from nanobot.session import Session


def chat(key: str, n: int = 4) -> Session:
    s = Session(key=key)
    for i in range(n):
        s.add_message("user" if i % 2 == 0 else "assistant", f"{key} message {i}")
    return s


def world(*sessions: Session):
    by_key = {s.key: s for s in sessions}
    return by_key.get


def test_parse_node_splits_on_the_last_hash_and_keeps_the_key_case():
    assert parse_node("websocket:AbC-1#12") == ("websocket:AbC-1", 12)
    for bad in ("nohash", "key#", "key#x", "#3", "key#-1"):
        with pytest.raises(ValueError):
            parse_node(bad)


def test_add_link_defaults_to_the_current_tip_and_stores_the_existing_edge_format():
    a, b = chat("cli:a"), chat("cli:b")
    link = add_link(a, ("cli:b", 3), None, world(a, b))
    assert (link.number, link.source, link.target) == (1, ("cli:b", 3), ("cli:a", 3))
    assert a.metadata["context_edges"] == [{"source": ["cli:b", 3], "target": ["cli:a", 3]}]
    assert [(x.source, x.target) for x in list_links(a)] == [(("cli:b", 3), ("cli:a", 3))]


def test_add_link_into_an_explicit_message():
    a, b = chat("cli:a"), chat("cli:b")
    assert add_link(a, ("cli:b", 1), 2, world(a, b)).target == ("cli:a", 2)


@pytest.mark.parametrize(
    "source, target, message",
    [
        (("cli:gone", 0), None, "not found"),
        (("cli:b", 9), None, "out of range"),
        (("cli:b", 0), 9, "out of range"),
        (("cli:a", 3), 3, "itself"),
    ],
)
def test_bad_links_are_rejected_and_change_nothing(source, target, message):
    a, b = chat("cli:a"), chat("cli:b")
    with pytest.raises(ValueError, match=message):
        add_link(a, source, target, world(a, b))
    assert list_links(a) == []


def test_command_turns_cannot_be_linked_and_an_empty_chat_has_nothing_to_link_into():
    a, b = chat("cli:a"), chat("cli:b")
    b.add_message("user", "/context graph", _command=True)
    with pytest.raises(ValueError, match="command"):
        add_link(a, ("cli:b", 4), None, world(a, b))
    with pytest.raises(ValueError, match="nothing to link into"):
        add_link(Session(key="cli:empty"), ("cli:b", 0), None, world(b))


def test_duplicates_and_the_cap_are_rejected():
    a, b = chat("cli:a", n=MAX_LINKS + 5), chat("cli:b", n=MAX_LINKS + 5)
    add_link(a, ("cli:b", 0), 1, world(a, b))
    with pytest.raises(ValueError, match="already"):
        add_link(a, ("cli:b", 0), 1, world(a, b))
    for i in range(1, MAX_LINKS):
        add_link(a, ("cli:b", i), 1, world(a, b))
    with pytest.raises(ValueError, match="at most"):
        add_link(a, ("cli:b", MAX_LINKS), 1, world(a, b))


def test_a_link_that_would_make_a_cycle_is_rejected():
    a, b = chat("cli:a"), chat("cli:b")
    # later message of the same chat into an earlier one: the target is already an ancestor
    with pytest.raises(ValueError, match="cycle"):
        add_link(a, ("cli:a", 3), 1, world(a, b))
    # b already depends on a#3; feeding b#2 back into a#3 would loop
    add_link(b, ("cli:a", 3), 1, world(a, b))
    with pytest.raises(ValueError, match="cycle"):
        add_link(a, ("cli:b", 2), 3, world(a, b))
    assert list_links(a) == []


def test_remove_link_renumbers_and_rejects_unknown_numbers():
    a, b = chat("cli:a"), chat("cli:b")
    for i in range(3):
        add_link(a, ("cli:b", i), 3, world(a, b))
    gone = remove_link(a, 2)
    assert gone.source == ("cli:b", 1)
    assert [(x.number, x.source[1]) for x in list_links(a)] == [(1, 0), (2, 2)]
    for bad in (0, 3, -1):
        with pytest.raises(ValueError, match="no link"):
            remove_link(a, bad)
    remove_link(a, 1)
    remove_link(a, 1)
    assert "context_edges" not in a.metadata  # nothing left: the key is dropped


def test_list_links_ignores_garbage_metadata():
    a = chat("cli:a")
    for junk in ("x", [1, "y", {"source": ["k"]}, {"source": ["k", "no"], "target": ["cli:a", 1]}]):
        a.metadata["context_edges"] = junk
        assert list_links(a) == []


def test_a_link_makes_graph_context_include_the_other_chat():
    """The Phase 6 demo, now created by a command instead of the seed script."""
    a, b = chat("cli:a", n=4), chat("cli:b", n=4)
    plain = GraphContextEngine(load_session=world(a, b)).build_context(a)
    assert not any(n.startswith("cli:b") for n in plain.node_ids)
    add_link(a, ("cli:b", 3), None, world(a, b))
    linked = GraphContextEngine(load_session=world(a, b)).build_context(a)
    assert {"cli:b#0", "cli:b#1", "cli:b#2", "cli:b#3"} <= set(linked.node_ids)
    assert linked.reasons["cli:b#3"] == "context"


def test_the_default_target_skips_trailing_command_turns():
    """Found in the browser: after any other /context command the chat ends in command turns."""
    a, b = chat("cli:a", n=4), chat("cli:b")
    a.add_message("user", "/context links", _command=True)
    a.add_message("assistant", "No links.", _command=True)
    assert add_link(a, ("cli:b", 3), None, world(a, b)).target == ("cli:a", 3)
    only_commands = Session(key="cli:z")
    only_commands.add_message("user", "/context graph", _command=True)
    with pytest.raises(ValueError, match="nothing to link into"):
        add_link(only_commands, ("cli:b", 0), None, world(b))
