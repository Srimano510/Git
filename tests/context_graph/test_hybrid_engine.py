from nanobot.config.schema import ContextGraphConfig
from nanobot.context_graph.engines import GraphContextEngine
from nanobot.context_graph.summaries import add_summary
from nanobot.session import Session
from nanobot.session.manager import SessionManager
from nanobot.utils.helpers import estimate_message_tokens

CFG = ContextGraphConfig()


def make_session(key="s", archived=0, extra=0):
    """Postgres decision at the start; unrelated chatter after it."""
    s = Session(key=key)
    s.add_message("user", "Which database should the orders service use?")
    s.add_message("assistant", "Use Postgres for the orders database, it handles transactions well.")
    for i in range(extra or 8):
        s.add_message("user", f"Tell me a fun fact about topic number {i}")
        s.add_message("assistant", f"Fun fact {i}: bananas are berries and tomatoes are fruit.")
    s.last_archived = archived
    return s


def engine(**kw):
    return GraphContextEngine(config=CFG, **kw)


def test_hybrid_recalls_an_archived_message_that_graph_mode_cannot_see():
    s = make_session(archived=6)
    q = "Remind me which database the orders service uses"

    graph = GraphContextEngine().build_context(s, max_tokens=100_000)
    hybrid = engine().build_context(s, max_tokens=100_000, query=q, hybrid=True)

    assert "Postgres" not in str([m["content"] for m in graph.messages])
    assert graph.recalled == ""
    assert "Postgres" in hybrid.recalled
    assert hybrid.messages == graph.messages  # recalled text is separate from replayed history
    assert hybrid.reasons["s#1"].startswith("vector (score ")
    assert "s#1" in hybrid.node_ids
    d = hybrid.diagnostics
    assert (d["phase"], d["pool"], d["semantic_included"]) == (4, "archived", 2)
    assert d["semantic_candidates"] == 6 and d["embed_ms"] >= 0


def test_query_defaults_to_the_latest_user_message():
    s = make_session(archived=6)
    s.add_message("user", "what database do the orders use again")
    out = engine().build_context(s, max_tokens=100_000, hybrid=True)
    assert "Postgres" in out.recalled


def test_hits_already_in_history_are_not_repeated():
    s = make_session(archived=0)  # nothing archived, big budget: everything is replayed
    out = engine().build_context(s, max_tokens=100_000, query="orders database postgres", hybrid=True)
    assert out.recalled == "" and out.diagnostics["semantic_included"] == 0


def test_summary_replaces_dropped_range_under_a_tight_budget():
    s = make_session(extra=12)
    add_summary(s, 0, 7, "Early on we chose Postgres for orders.")
    full = engine().build_context(s, max_tokens=100_000, query="zzz", hybrid=True)
    tail_tokens = sum(estimate_message_tokens(m) for m in full.messages[-6:])
    out = engine().build_context(s, max_tokens=tail_tokens + 40, query="zzz", hybrid=True)

    assert "Early on we chose Postgres" in out.recalled
    assert out.reasons["s#0"].startswith("summary (covers 0-7)")
    assert out.diagnostics["summaries_used"] == 1
    assert out.token_count <= tail_tokens + 40
    assert len(out.messages) < len(full.messages)


def test_summary_unused_when_its_range_is_still_replayed():
    s = make_session()
    add_summary(s, 0, 3, "Early summary.")
    out = engine().build_context(s, max_tokens=100_000, query="zzz", hybrid=True)
    assert out.recalled == "" and out.diagnostics["summaries_used"] == 0


def test_recalled_block_respects_its_own_token_budget():
    s = make_session(archived=18)
    cfg = ContextGraphConfig(recall_token_budget=40, semantic_top_k=10, semantic_min_score=0.0)
    out = GraphContextEngine(config=cfg).build_context(
        s, max_tokens=100_000, query="fun fact about bananas tomatoes topic orders database", hybrid=True
    )
    assert out.recalled
    assert estimate_message_tokens({"content": out.recalled}) <= 40 + 25  # header allowance


def test_embedder_failure_degrades_to_plain_graph_history():
    class Boom:
        def embed(self, text):
            raise RuntimeError("no embeddings today")

    s = make_session(archived=6)
    graph = GraphContextEngine().build_context(s, max_tokens=100_000)
    out = engine(embedder=Boom()).build_context(s, max_tokens=100_000, query="database", hybrid=True)
    assert out.messages == graph.messages
    assert out.recalled == ""
    assert "RuntimeError" in out.diagnostics["semantic_error"]
    assert out.diagnostics["fallback"] is None


def test_family_pool_reaches_a_sibling_branch_but_archived_pool_does_not(tmp_path):
    m = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    src = m.get_or_create("websocket:src")
    for r, t in [("user", "Start"), ("assistant", "Hello there")]:
        src.add_message(r, t)
    m.save(src)
    kid_a = m.fork_session_before_user_index(src.key, "websocket:a", 1)
    kid_a.add_message("user", "In this branch we selected Kafka for the event streaming layer")
    kid_a.add_message("assistant", "Kafka it is, partitioned by tenant.")
    m.save(kid_a)
    kid_b = m.fork_session_before_user_index(src.key, "websocket:b", 1)
    kid_b.add_message("user", "Which event streaming layer did we select?")
    m.save(kid_b)

    eng = engine(load_session=m.read_session_snapshot, list_sessions=m.list_sessions)
    q = "Which event streaming layer did we select"
    archived = eng.build_context(kid_b, max_tokens=100_000, query=q, hybrid=True, pool="archived")
    family = eng.build_context(kid_b, max_tokens=100_000, query=q, hybrid=True, pool="family")

    assert "Kafka" not in archived.recalled
    assert "Kafka" in family.recalled
    assert family.diagnostics["pool"] == "family"
    assert any(v.startswith("vector") and k.startswith("websocket:a#") for k, v in family.reasons.items())


def test_graph_strategy_output_is_unchanged_by_the_hybrid_arguments_being_absent():
    s = make_session(archived=6)
    a = GraphContextEngine().build_context(s, max_tokens=100_000)
    b = engine().build_context(s, max_tokens=100_000, query="orders", hybrid=False)
    assert a.messages == b.messages and b.recalled == "" and b.diagnostics["phase"] == 3


# --- the recall cut-off follows the embedder (dense models score unrelated text higher) -------


class Scored:
    """Embedder with a chosen similarity per text: one relevant message, the rest 'noise'."""

    def __init__(self, default_min_score):
        self.name = "scored"
        self.default_min_score = default_min_score

    def embed(self, text):
        # query and the Postgres message share axis 0; all other texts sit at cosine 0.2 to the query
        if "orders" in text:
            return {0: 1.0}
        return {0: 0.2, 1: 0.9797958971132712}


def test_recall_cutoff_defaults_to_the_embedders_own_value():
    s = make_session(archived=18)
    q = "orders database"
    strict = GraphContextEngine(config=CFG, embedder=Scored(0.3)).build_context(s, query=q, hybrid=True)
    loose = GraphContextEngine(config=CFG, embedder=Scored(0.1)).build_context(s, query=q, hybrid=True)
    assert strict.diagnostics["semantic_included"] == 2  # only the two 'orders' messages clear 0.3
    assert loose.diagnostics["semantic_included"] == CFG.semantic_top_k  # noise at 0.2 clears 0.1


def test_an_explicit_min_score_beats_the_embedders_default():
    s = make_session(archived=18)
    cfg = ContextGraphConfig(semantic_min_score=0.1)
    out = GraphContextEngine(config=cfg, embedder=Scored(0.3)).build_context(s, query="orders database", hybrid=True)
    assert out.diagnostics["semantic_included"] == cfg.semantic_top_k
