from nanobot.context_graph.embed import HashEmbedder
from nanobot.context_graph.recall import pool_candidates, recall
from nanobot.context_graph.tree import load_family
from nanobot.session.manager import SessionManager


def msg(role, content, **extra):
    return {"role": role, "content": content, **extra}


E = HashEmbedder()


def run(query, candidates, **kw):
    return recall(query, candidates, E, **kw)


def test_ranks_the_planted_relevant_message_first_and_honours_top_k():
    cands = [
        (("s", 0), msg("user", "What did we decide about the orders database?")),
        (("s", 1), msg("assistant", "We chose Postgres for the orders database.")),
        (("s", 2), msg("user", "Lisbon weather is sunny")),
        (("s", 3), msg("assistant", "Unrelated pasta recipe with tomatoes")),
    ]
    hits = run("remind me which database we chose for orders", cands, top_k=2)
    assert [h.node for h in hits][0] == ("s", 1)
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
    assert "Postgres" in hits[0].text


def test_min_score_filters_weak_matches():
    cands = [(("s", 0), msg("user", "Lisbon weather is sunny"))]
    assert run("orders database postgres", cands, min_score=0.15) == []


def test_skips_ineligible_and_excluded_candidates():
    cands = [
        (("s", 0), msg("tool", "postgres orders database result")),
        (("s", 1), msg("assistant", "", tool_calls=[{"id": "t"}])),
        (("s", 2), msg("user", "postgres orders database", _hidden_history=True)),
        (("s", 3), msg("system", "postgres orders database")),
        (("s", 4), msg("user", "postgres orders database")),
        (("s", 5), msg("user", "postgres orders database again")),
    ]
    hits = run("postgres orders database", cands, exclude={("s", 5)})
    assert [h.node for h in hits] == [("s", 4)]


def test_content_blocks_and_empty_query():
    cands = [(("s", 0), msg("user", [{"type": "text", "text": "postgres orders database"}]))]
    assert [h.node for h in run("postgres database", cands)] == [("s", 0)]
    assert run("", cands) == []


def test_ties_break_by_node_for_stable_order():
    cands = [(("s", 2), msg("user", "postgres")), (("s", 1), msg("user", "postgres"))]
    assert [h.node for h in run("postgres", cands)] == [("s", 1), ("s", 2)]


def make_family(tmp_path):
    m = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    src = m.get_or_create("websocket:src")
    for r, t in [("user", "Start"), ("assistant", "Hi"), ("user", "Pick a database"), ("assistant", "Postgres")]:
        src.add_message(r, t)
    m.save(src)
    kid = m.fork_session_before_user_index(src.key, "websocket:kid", 1)
    kid.add_message("user", "Sibling only question")
    m.save(kid)
    other = m.get_or_create("websocket:other")
    other.add_message("user", "unrelated chat")
    m.save(other)
    return m, src, kid


def test_archived_pool_is_own_ancestry_not_kept_and_excludes_siblings(tmp_path):
    m, src, kid = make_family(tmp_path)
    ancestry = [("websocket:src", 0), ("websocket:src", 1)]
    sessions = {"websocket:src": m.read_session_snapshot(src.key)}
    kept = {("websocket:src", 1)}
    cands = pool_candidates("archived", ancestry, kept, sessions, None)
    assert [n for n, _ in cands] == [("websocket:src", 0)]


def test_family_pool_adds_sibling_branches_but_not_unrelated_chats(tmp_path):
    m, src, kid = make_family(tmp_path)
    fam = load_family(kid.key, m.list_sessions(), m.read_session_snapshot)
    # kid's ancestry: src#0, src#1 (copied prefix) and its own new message
    ancestry = [("websocket:src", 0), ("websocket:src", 1), (kid.key, 2)]
    kept = {(kid.key, 2)}
    cands = dict(pool_candidates("family", ancestry, kept, fam.sessions, fam))
    assert ("websocket:src", 0) in cands  # ancestry not kept
    assert ("websocket:src", 3) in cands  # sibling continuation on the source branch
    assert (kid.key, 2) not in cands  # kept
    assert not any(k == "websocket:other" for k, _ in cands)
