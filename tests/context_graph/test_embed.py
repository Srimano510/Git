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


# --- Phase 7: a real local embedder behind the same protocol -----------------------------

import importlib.util  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from loguru import logger  # noqa: E402

from nanobot.config.schema import ContextGraphConfig  # noqa: E402
from nanobot.context_graph import embed as embed_module  # noqa: E402
from nanobot.context_graph.embed import Model2VecEmbedder, make_embedder  # noqa: E402


class FakeModel:
    """Stands in for model2vec's StaticModel: 3 dims, counts calls."""

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        return [[3.0, 4.0, 0.0] if t == "alpha" else [0.0, 0.0, 0.0] if not t else [0.0, 1.0, 0.0]
                for t in texts]


def test_model2vec_embedder_normalises_caches_and_handles_empty_text():
    model = FakeModel()
    e = Model2VecEmbedder(model=model)
    v = e.embed("alpha")
    assert v == pytest.approx({0: 0.6, 1: 0.8})  # zero entries are dropped, vector is unit length
    assert e.embed("alpha") == v and model.calls == 1  # second call is served from the cache
    assert e.embed("") == {}  # an all-zero vector is "no meaning", like the hashed embedder
    assert e.name == "model2vec"


def test_model2vec_embedder_cache_is_bounded():
    model = FakeModel()
    e = Model2VecEmbedder(model=model, cache_size=2)
    for text in ("a", "b", "c"):
        e.embed(text)
    e.embed("a")  # evicted by "c", so it is encoded again
    assert model.calls == 4


def test_choosing_hash_never_loads_a_model():
    assert isinstance(make_embedder(ContextGraphConfig(semantic_embedder="hash")), HashEmbedder)
    assert HashEmbedder().name == "hash"


def test_failures_fall_back_to_hashed_words_and_only_an_explicit_choice_warns(monkeypatch):
    def broken(*a, **k):
        raise OSError("model not cached")

    monkeypatch.setattr(embed_module, "Model2VecEmbedder", broken)
    monkeypatch.setattr(embed_module, "_EMBEDDERS", {})
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="WARNING")
    try:
        auto = ContextGraphConfig(semantic_embedder="auto")
        assert isinstance(make_embedder(auto), HashEmbedder)
        assert lines == []  # "auto" without the extra or the model is a normal setup, not a problem
        explicit = ContextGraphConfig(semantic_embedder="model2vec")
        assert isinstance(make_embedder(explicit), HashEmbedder)
        assert make_embedder(explicit) is make_embedder(explicit)  # decided once, then reused
    finally:
        logger.remove(sink)
    assert len(lines) == 1 and "hashed words" in lines[0]


def test_auto_never_downloads_inside_a_turn_but_an_explicit_choice_may(monkeypatch):
    monkeypatch.setattr(embed_module, "_EMBEDDERS", {})
    tried: list[bool] = []

    class Spy:
        def __init__(self, model_name, *, allow_download, **kw):
            tried.append(allow_download)

    monkeypatch.setattr(embed_module, "Model2VecEmbedder", Spy)
    make_embedder(ContextGraphConfig(semantic_embedder="auto", semantic_model="a/auto-model"))
    make_embedder(ContextGraphConfig(semantic_embedder="model2vec", semantic_model="a/explicit-model"))
    # "auto" must never start a download inside a turn; asking for model2vec explicitly may.
    assert tried == [False, True]


def _cached_real_model() -> Path | None:
    hub = Path.home() / ".nanobot" / "models" / "hub"
    if importlib.util.find_spec("model2vec") is None or not hub.exists():
        return None
    return hub if any(hub.glob("models--minishlab--potion-base-8M")) else None


@pytest.mark.skipif(_cached_real_model() is None, reason="model2vec model not downloaded")
def test_real_model_matches_meaning_not_just_shared_words():
    e = Model2VecEmbedder(cache_dir=_cached_real_model(), allow_download=False)
    assert cosine(e.embed("car"), e.embed("automobile")) > cosine(e.embed("car"), e.embed("banana")) + 0.4
    q = e.embed("database for the orders service")
    assert cosine(q, e.embed("we chose Postgres to store orders")) > 0.4
    assert cosine(q, e.embed("bananas are berries and tomatoes are fruit")) < 0.2
    # the hashed embedder cannot do the first one at all
    h = HashEmbedder()
    assert cosine(h.embed("car"), h.embed("automobile")) == 0.0


def test_each_embedder_carries_its_own_recall_cutoff():
    # dense-model scores for unrelated text reach ~0.2 while real matches stay above ~0.4
    assert HashEmbedder().default_min_score == 0.15
    assert Model2VecEmbedder(model=FakeModel()).default_min_score == 0.30


# --- the loader must not touch the network when the model is already cached ------------------


class FakeHub:
    def __init__(self, cached: bool):
        self.cached, self.calls = cached, []

    def snapshot_download(self, repo, *, local_files_only, **kw):
        self.calls.append(local_files_only)
        if local_files_only and not self.cached:
            raise FileNotFoundError("not in the local cache")
        return f"/models/{repo}"


def patch_loader(monkeypatch, hub):
    import importlib

    import model2vec

    real = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", lambda name, *a: hub if name == "huggingface_hub" else real(name, *a))
    loaded = []
    monkeypatch.setattr(model2vec.StaticModel, "from_pretrained", classmethod(lambda cls, path, *a, **k: loaded.append(path) or FakeModel()))
    return loaded


@pytest.mark.skipif(importlib.util.find_spec("model2vec") is None, reason="model2vec not installed")
def test_a_cached_model_is_loaded_without_any_network_call_even_when_downloads_are_allowed(monkeypatch):
    hub = FakeHub(cached=True)
    loaded = patch_loader(monkeypatch, hub)
    Model2VecEmbedder("org/m", allow_download=True)
    assert hub.calls == [True] and loaded == ["/models/org/m"]  # one local lookup, no download attempt


@pytest.mark.skipif(importlib.util.find_spec("model2vec") is None, reason="model2vec not installed")
def test_a_missing_model_is_downloaded_only_when_allowed(monkeypatch):
    hub = FakeHub(cached=False)
    loaded = patch_loader(monkeypatch, hub)
    Model2VecEmbedder("org/m", allow_download=True)
    assert hub.calls == [True, False] and loaded == ["/models/org/m"]  # local first, then the one download

    hub2 = FakeHub(cached=False)
    patch_loader(monkeypatch, hub2)
    with pytest.raises(FileNotFoundError):
        Model2VecEmbedder("org/m", allow_download=False)
    assert hub2.calls == [True]  # never went online


def test_prefetch_downloads_into_the_data_dir_of_the_config_it_is_given(monkeypatch, tmp_path, capsys):
    """`python -m nanobot.context_graph.embed --config <demo config>` must fill that instance's
    model directory, not the default one, or "auto" would silently fall back to hashed words."""
    import json

    from nanobot.config.paths import get_data_dir
    from nanobot.context_graph.embed import main as prefetch

    config = tmp_path / "demo" / "config.json"
    config.parent.mkdir()
    config.write_text(json.dumps({}))
    seen = {}

    class Spy:
        default_min_score = 0.3

        def __init__(self, model_name, *, allow_download, **kw):
            seen["model"], seen["download"] = model_name, allow_download
            seen["dir"] = embed_module._models_dir()

        def embed(self, text):
            return {0: 1.0}

    monkeypatch.undo()  # the autouse isolation patches _models_dir; this test wants the real one
    monkeypatch.setattr(embed_module, "Model2VecEmbedder", Spy)
    try:
        assert prefetch(["org/model", "--config", str(config)]) == 0
        assert seen["model"] == "org/model" and seen["download"] is True
        assert str(seen["dir"]).startswith(str(config.parent))  # under the instance, not ~/.nanobot
        assert "ready" in capsys.readouterr().out
    finally:
        import nanobot.config.loader as loader

        loader._current_config_path = None  # do not leak the demo config into later tests
    assert get_data_dir() != config.parent
