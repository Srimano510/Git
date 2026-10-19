from nanobot.config.schema import ContextGraphConfig
from nanobot.context_graph import GraphContextEngine
from nanobot.context_graph.embed import HashEmbedder
from nanobot.context_graph.prune import prune_by_relevance, split_turns
from nanobot.context_graph.summaries import add_summary
from nanobot.session import Session
from nanobot.utils.helpers import estimate_message_tokens

QUERY = "which database did we pick for the orders service"
FACT = "We decided to use Postgres as the database for the orders service, it handles transactions."
NOISE = "Bananas are berries and tomatoes are fruit, botanically speaking, which surprises people."


def turn(user: str, assistant: str) -> list[dict]:
    return [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]


def chat(n_noise_before=5, n_noise_after=4) -> list[dict]:
    """noise turns, then one relevant turn, then more noise turns."""
    msgs: list[dict] = []
    for i in range(n_noise_before):
        msgs += turn(f"fun fact {i}?", f"{NOISE} ({i})")
    msgs += turn("Which database should the orders service use?", FACT)
    for i in range(n_noise_after):
        msgs += turn(f"another fun fact {i}?", f"{NOISE} ({i})")
    return msgs


def tokens(msgs, idx=None) -> int:
    return sum(estimate_message_tokens(m) for j, m in enumerate(msgs) if idx is None or j in idx)


def test_split_turns_keeps_tool_calls_with_their_turn():
    msgs = [
        {"role": "assistant", "content": "welcome"},  # before any user message: its own group
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "result"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    assert split_turns(msgs) == [[0], [1, 2, 3, 4], [5, 6]]
    assert split_turns([]) == []


def test_nothing_is_pruned_when_the_replay_fits_the_budget():
    msgs = chat()
    assert prune_by_relevance(msgs, QUERY, HashEmbedder(), budget=tokens(msgs), keep_recent_turns=2) is None


def test_over_budget_keeps_recent_turns_and_the_relevant_old_turn_and_drops_noise():
    msgs = chat()
    budget = tokens(msgs) // 3
    result = prune_by_relevance(msgs, QUERY, HashEmbedder(), budget=budget, keep_recent_turns=2)
    assert result is not None
    kept = result.kept
    assert kept == sorted(kept)  # chronological
    assert {10, 11} <= set(kept)  # the relevant turn (messages 10 and 11) survives
    assert {len(msgs) - 4, len(msgs) - 3, len(msgs) - 2, len(msgs) - 1} <= set(kept)  # last two turns
    assert len(kept) < len(msgs) and tokens(msgs, set(kept)) <= budget
    assert result.scores[10] > 0.2 and result.scores[11] == result.scores[10]  # one score per turn
    assert not (set(kept) & {0, 1, 2, 3})  # early noise is gone


def test_a_turn_is_kept_or_dropped_as_a_whole():
    msgs = chat()
    msgs[1] = {"role": "assistant", "content": "", "tool_calls": [{"id": "9"}]}
    msgs.insert(2, {"role": "tool", "tool_call_id": "9", "content": NOISE})
    msgs.insert(3, {"role": "assistant", "content": NOISE})
    result = prune_by_relevance(msgs, QUERY, HashEmbedder(), budget=tokens(msgs) // 3, keep_recent_turns=2)
    assert result is not None
    for group in split_turns(msgs):
        inside = [i in set(result.kept) for i in group]
        assert all(inside) or not any(inside)


def test_recent_turns_are_protected_even_when_they_alone_exceed_the_budget():
    msgs = chat()
    result = prune_by_relevance(msgs, QUERY, HashEmbedder(), budget=10, keep_recent_turns=2)
    assert result is not None and result.kept == [len(msgs) - 4, len(msgs) - 3, len(msgs) - 2, len(msgs) - 1]


def test_empty_query_falls_back_to_recency():
    msgs = chat()
    result = prune_by_relevance(msgs, "", HashEmbedder(), budget=tokens(msgs) // 2, keep_recent_turns=1)
    assert result is not None
    assert result.kept[-2:] == [len(msgs) - 2, len(msgs) - 1]
    assert result.kept == list(range(result.kept[0], len(msgs)))  # a contiguous newest suffix


# --- the engine ---------------------------------------------------------------------------


def session_of(msgs) -> Session:
    s = Session(key="s")
    s.messages = [dict(m) for m in msgs]
    return s


def engine(**cfg) -> GraphContextEngine:
    return GraphContextEngine(config=ContextGraphConfig(semantic_embedder="hash", **cfg))


def test_budget_zero_keeps_todays_behaviour():
    msgs = chat()
    result = engine().build_context(session_of(msgs), query=QUERY)
    assert len(result.messages) == len(msgs) and "pruned_by_relevance" not in result.diagnostics


def test_graph_mode_prunes_by_relevance_under_the_dedicated_budget():
    msgs = chat()
    budget = tokens(msgs) // 3
    result = engine(graph_token_budget=budget).build_context(session_of(msgs), query=QUERY)
    ids = set(result.node_ids)
    assert {"s#10", "s#11"} <= ids and "s#0" not in ids
    assert result.token_count <= budget
    assert result.reasons["s#10"].startswith("relevance (score ")
    assert result.reasons[f"s#{len(msgs) - 1}"] == "current"  # protected recent turn keeps its graph reason
    assert result.diagnostics["pruned_by_relevance"] == len(msgs) - len(result.messages)
    assert result.diagnostics["graph_budget"] == budget and result.diagnostics["fallback"] is None
    assert msgs[11]["content"] in [m["content"] for m in result.messages]


def test_pruned_messages_are_still_in_chronological_order_and_legal():
    msgs = chat()
    result = engine(graph_token_budget=tokens(msgs) // 3).build_context(session_of(msgs), query=QUERY)
    idx = [int(n.split("#")[1]) for n in result.node_ids]
    assert idx == sorted(idx)
    assert result.messages[0]["role"] == "user"  # history never starts mid-turn


def test_hybrid_respects_the_graph_budget_and_still_recalls():
    msgs = chat()
    s = session_of(msgs)
    budget = tokens(msgs) // 3
    result = engine(graph_token_budget=budget).build_context(s, query=QUERY, hybrid=True)
    assert result.token_count <= budget and result.diagnostics["pruned_by_relevance"] > 0
    assert result.diagnostics["embedder"] == "hash"


def test_a_summary_stands_in_for_a_range_the_budget_pruned():
    msgs = chat(n_noise_before=6, n_noise_after=3)
    s = session_of(msgs)
    add_summary(s, 0, 11, "Early on: lots of small talk about fruit.")  # covers only noise turns 0-5
    result = engine(graph_token_budget=tokens(msgs) // 3).build_context(s, query=QUERY, hybrid=True)
    assert "[summary of messages 0-11] Early on: lots of small talk about fruit." in result.recalled


def test_an_embedder_failure_skips_pruning_but_not_the_turn():
    class Broken:
        name = "broken"

        def embed(self, text):
            raise RuntimeError("boom")

    msgs = chat()
    eng = GraphContextEngine(
        config=ContextGraphConfig(graph_token_budget=tokens(msgs) // 3), embedder=Broken()
    )
    result = eng.build_context(session_of(msgs), query=QUERY)
    assert result.diagnostics["fallback"] is None
    assert result.diagnostics["prune_error"] == "RuntimeError: boom"
    assert result.messages  # the turn still gets (budget-trimmed) history


def test_a_generated_summary_stands_in_for_a_pruned_range_too():
    msgs = chat(n_noise_before=6, n_noise_after=3)
    s = session_of(msgs)
    add_summary(s, 0, 11, "Early small talk about fruit, condensed by the model.", source="llm")
    out = engine(graph_token_budget=tokens(msgs) // 3).build_context(s, query=QUERY, hybrid=True)
    assert "[generated summary of messages 0-11] Early small talk about fruit" in out.recalled
    assert out.reasons["s#0"] == "summary (generated, covers 0-11)"


# --- a summary makes the turns it covers the first to go ------------------------------------


def test_turns_fully_covered_by_a_summary_are_dropped_before_ranking():
    msgs = chat()
    covered = set(range(0, 10))  # the five noise turns before the relevant one
    plain = prune_by_relevance(msgs, QUERY, HashEmbedder(), budget=tokens(msgs) * 2 // 3, keep_recent_turns=2)
    with_summary = prune_by_relevance(
        msgs, QUERY, HashEmbedder(), budget=tokens(msgs) * 2 // 3, keep_recent_turns=2, covered=covered
    )
    assert plain is not None and with_summary is not None
    assert set(plain.kept) & covered  # the spare budget keeps some of that small talk...
    assert not set(with_summary.kept) & covered  # ...but not once a summary stands in for it
    assert {10, 11} <= set(with_summary.kept)  # the relevant turn still wins on merit


def test_covered_recent_turns_and_partly_covered_turns_are_not_dropped_by_that_rule():
    msgs = chat()
    last = len(msgs) - 1
    result = prune_by_relevance(
        msgs, QUERY, HashEmbedder(), budget=tokens(msgs) // 2, keep_recent_turns=2,
        covered={last, last - 1, 0},  # a recent turn, and only the first half of turn 0
    )
    assert result is not None and {last - 1, last} <= set(result.kept)  # recent turns are protected
    assert split_turns(msgs)[0] == [0, 1]  # message 1 of that turn is not covered, so it still competes


def test_hybrid_uses_a_summary_over_a_range_that_pruning_would_only_partly_drop():
    msgs = chat(n_noise_before=8, n_noise_after=3)
    s = session_of(msgs)
    add_summary(s, 0, 15, "The model's gist of the early small talk.", source="llm")  # all 8 noise turns
    budget = tokens(msgs) * 2 // 3
    out = engine(graph_token_budget=budget).build_context(s, query=QUERY, hybrid=True)
    assert "[generated summary of messages 0-15] The model's gist" in out.recalled
    assert not any(int(n.split("#")[1]) < 16 for n in out.node_ids if not out.reasons[n].startswith("summary"))
    # graph mode never shows summaries, so the covered turns keep competing for the budget there
    graph = engine(graph_token_budget=budget).build_context(s, query=QUERY)
    assert any(int(n.split("#")[1]) < 16 for n in graph.node_ids)
