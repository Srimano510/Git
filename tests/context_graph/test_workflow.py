from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.context_graph import ConversationGraph, EdgeType, GraphContextEngine
from nanobot.context_graph.observability import ContextResult
from nanobot.context_graph.resolver import get_ancestor_context
from nanobot.context_graph.workflow import WORKFLOW_EDGES, build_workflow
from nanobot.session import Session
from nanobot.session.manager import SessionManager

QUERY = "Remind me which database the orders service uses"


def make_loop(tmp_path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "m"
    return AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path, model="m",
        context_window_tokens=100_000,
    )


def archived_session(key="cli:c"):
    s = Session(key=key)
    s.add_message("user", "Which database should the orders service use?")
    s.add_message("assistant", "Use Postgres for the orders database.")
    for i in range(6):
        s.add_message("user", f"fun fact request {i}")
        s.add_message("assistant", f"bananas are berries {i}")
    s.last_archived = 4
    return s


def hybrid_result(**diag) -> ContextResult:
    return ContextResult(
        strategy="hybrid", messages=[], node_ids=["s#0", "s#1"], token_count=42,
        retrieval_ms=10.0,
        diagnostics={
            "pool": "archived", "visited": 5, "returned": 4, "pruned": 1, "branch_count": 0,
            "semantic_candidates": 3, "semantic_hits": 2, "semantic_included": 1,
            "summaries_used": 0, "embed_ms": 4.0, "fallback": None, **diag,
        },
    )


def edges_of(wf):
    return {(e["source"], e["target"], e["type"]) for e in wf["edges"]}


def test_default_traversal_ignores_workflow_edges():
    g = ConversationGraph()
    g.add_edge(("s", 0), ("s", 1), EdgeType.REPLY)
    g.add_edge(("workflow", 0), ("s", 1), EdgeType.TRIGGERS)
    g.add_edge(("workflow", 1), ("s", 1), EdgeType.FEEDS)
    nodes, _ = get_ancestor_context(g, ("s", 1))
    assert nodes == [("s", 0), ("s", 1)]


def test_hybrid_trace_has_the_parallel_branch_in_topological_order():
    wf = build_workflow(hybrid_result(), at=7)
    assert wf["at"] == 7 and wf["strategy"] == "hybrid"
    assert [n["label"] for n in wf["nodes"]] == [
        "ContextStrategySelection", "GraphTraversal", "SemanticSearch",
        "ContextMerge", "PromptBuild", "LLMCall",
    ]
    assert edges_of(wf) == {
        ("workflow#0", "workflow#1", "TRIGGERS"), ("workflow#0", "workflow#2", "TRIGGERS"),
        ("workflow#1", "workflow#3", "FEEDS"), ("workflow#2", "workflow#3", "FEEDS"),
        ("workflow#3", "workflow#4", "FEEDS"), ("workflow#4", "workflow#5", "FEEDS"),
    }
    g = ConversationGraph()
    for e in wf["edges"]:
        s, t = (("workflow", int(x.split("#")[1])) for x in (e["source"], e["target"]))
        g.add_edge(s, t, EdgeType(e["type"]))
    order, _ = get_ancestor_context(g, ("workflow", 5), WORKFLOW_EDGES)
    assert [i for _, i in order] == [0, 1, 2, 3, 4, 5]


def test_graph_trace_has_no_semantic_search():
    r = hybrid_result()
    r.strategy = "graph"
    wf = build_workflow(r, at=0)
    assert [n["label"] for n in wf["nodes"]] == [
        "ContextStrategySelection", "GraphTraversal", "ContextMerge", "PromptBuild", "LLMCall",
    ]
    ids = {n["id"] for n in wf["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in wf["edges"])
    assert ("workflow#0", "workflow#1", "TRIGGERS") in edges_of(wf)


def test_details_carry_real_numbers_and_errors():
    wf = build_workflow(hybrid_result(), at=0)
    by = {n["label"]: n for n in wf["nodes"]}
    assert by["GraphTraversal"]["ms"] == 6.0 and by["SemanticSearch"]["ms"] == 4.0
    assert "visited 5" in by["GraphTraversal"]["detail"] and "pruned 1" in by["GraphTraversal"]["detail"]
    assert "pool=archived" in by["ContextStrategySelection"]["detail"]
    assert "42 tokens" in by["PromptBuild"]["detail"]
    assert "ms" not in by["PromptBuild"] and "ms" not in by["LLMCall"]

    bad = build_workflow(hybrid_result(semantic_error="Boom: x", fallback="Err: y"), at=0)
    by = {n["label"]: n for n in bad["nodes"]}
    assert "Boom: x" in by["SemanticSearch"]["detail"]
    assert "Err: y" in by["GraphTraversal"]["detail"]


def test_workflow_never_reaches_context_messages_or_node_ids():
    s = archived_session()
    s.metadata["_last_workflow"] = build_workflow(hybrid_result(), at=0)
    result = GraphContextEngine().build_context(s, hybrid=True, query=QUERY)
    plain = GraphContextEngine().build_context(archived_session(), hybrid=True, query=QUERY)
    assert result.messages == plain.messages and result.node_ids == plain.node_ids
    assert not any("workflow" in n for n in result.node_ids)
    assert not any("LLMCall" in str(m) for m in result.messages)
    assert len(s.messages) == 14


def test_graph_and_hybrid_turns_record_a_trace_linear_and_subagent_do_not(tmp_path):
    loop = make_loop(tmp_path)
    s = archived_session()
    loop._graph_context(s, "hybrid", QUERY, extend_to_user=False)
    wf = s.metadata["_last_workflow"]
    assert wf["at"] == 14 and wf["strategy"] == "hybrid"
    assert len(wf["nodes"]) == 6

    g = archived_session()
    loop._graph_context(g, "graph", QUERY, extend_to_user=False)
    assert len(g.metadata["_last_workflow"]["nodes"]) == 5

    sub = archived_session()
    loop._graph_context(sub, "graph", None, extend_to_user=True)
    assert "_last_workflow" not in sub.metadata


def test_forks_do_not_inherit_the_last_workflow(tmp_path):
    m = SessionManager(tmp_path / "ws", sessions_root=tmp_path / "files")
    src = m.get_or_create("websocket:src")
    src.add_message("user", "q")
    src.add_message("assistant", "a")
    src.metadata["_last_workflow"] = build_workflow(hybrid_result(), at=0)
    m.save(src)
    kid = m.fork_session_before_user_index(src.key, "websocket:kid", 1)
    assert "_last_workflow" not in kid.metadata
