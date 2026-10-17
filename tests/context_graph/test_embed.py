import os
import subprocess
import sys

from nanobot.context_graph.embed import HashEmbedder, cosine


def test_related_text_scores_above_unrelated():
    e = HashEmbedder()
    query = e.embed("which database did we pick for the orders service")
    related = e.embed("We decided to use Postgres as the database for orders")
    unrelated = e.embed("The weather in Lisbon is sunny today")
    assert cosine(query, related) > cosine(query, unrelated)
    assert cosine(query, unrelated) < 0.1


def test_case_punctuation_and_stopwords_do_not_matter():
    e = HashEmbedder()
    assert cosine(e.embed("Postgres, DATABASE!"), e.embed("the database postgres")) > 0.99


def test_empty_and_stopword_only_text_is_safe():
    e = HashEmbedder()
    assert e.embed("") == {}
    assert e.embed("the and of") == {}
    assert cosine({}, e.embed("anything here")) == 0.0
    assert cosine({}, {}) == 0.0


def test_vectors_are_normalised():
    v = HashEmbedder().embed("alpha beta beta gamma")
    assert abs(sum(x * x for x in v.values()) - 1.0) < 1e-9


def test_deterministic_across_processes_with_different_hash_seeds():
    code = (
        "from nanobot.context_graph.embed import HashEmbedder;"
        "v=HashEmbedder().embed('orders database postgres');"
        "print(sorted(v.items()))"
    )
    outs = {
        subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for seed in ("1", "2")
    }
    assert len(outs) == 1
