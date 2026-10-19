"""Text embedding for semantic recall and relevance pruning.

Two embedders behind one protocol: a dependency-free hashed bag-of-words (matches shared
words, not meaning) and, when the optional ``semantic`` extra is installed and its model has
been downloaded, a small local static-embedding model (matches meaning). ``make_embedder``
picks one from the config and falls back to the hashed one rather than failing a turn.
"""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter, OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import ContextGraphConfig

Vector = dict[int, float]

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i in is it of on or that the this to was "
    "we what which with you".split()
)


class Embedder(Protocol):
    default_min_score: float

    def embed(self, text: str) -> Vector: ...


class HashEmbedder:
    """Sparse, L2-normalised term vectors. ``zlib.crc32`` keeps buckets stable across runs."""

    name = "hash"
    default_min_score = 0.15  # shared words only: unrelated text scores ~0

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed(self, text: str) -> Vector:
        counts = Counter(
            zlib.crc32(w.encode()) % self.dim
            for w in _WORD.findall(text.lower())
            if w not in _STOPWORDS
        )
        vec = {i: 1.0 + math.log(c) for i, c in counts.items()}
        norm = math.sqrt(sum(x * x for x in vec.values()))
        return {i: x / norm for i, x in vec.items()} if norm else {}


def cosine(a: Vector, b: Vector) -> float:
    """Dot product of two normalised vectors."""
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(i, 0.0) for i, x in a.items())


_MODEL_FILES = ["config.json", "model.safetensors", "tokenizer.json"]


def _models_dir() -> Path:
    """Where model downloads live: the nanobot data dir, never the global Hugging Face cache."""
    from nanobot.config.paths import get_runtime_subdir

    return get_runtime_subdir("models") / "hub"


class Model2VecEmbedder:
    """Dense, unit-length vectors from a small local static-embedding model (model2vec).

    Loads from the local cache; ``allow_download`` lets it fetch the model once. Vectors are
    returned as ``{index: value}`` so ``cosine`` and the rest of the code need no change.
    Embeddings are cached per text (bounded), so a turn embeds each message once.
    """

    name = "model2vec"
    default_min_score = 0.30  # measured: unrelated text scores up to ~0.2, real matches 0.4 and up

    def __init__(
        self,
        model_name: str = "minishlab/potion-base-8M",
        *,
        allow_download: bool = False,
        cache_dir: Path | None = None,
        cache_size: int = 4096,
        model: Any = None,
    ) -> None:
        self.model_name = model_name
        self._cache_size = cache_size
        self._cache: OrderedDict[str, Vector] = OrderedDict()
        self._model = model if model is not None else self._load(model_name, allow_download, cache_dir)

    @staticmethod
    def _load(model_name: str, allow_download: bool, cache_dir: Path | None) -> Any:
        import os

        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # noisy and harmless on Windows
        import importlib

        from model2vec import StaticModel

        hub: Any = importlib.import_module("huggingface_hub")  # its overloads are partly untyped
        def fetch(local_only: bool) -> str:
            return hub.snapshot_download(
                model_name,
                cache_dir=cache_dir or _models_dir(),
                allow_patterns=_MODEL_FILES,  # a static model is just these; skip the repo's extras
                local_files_only=local_only,
            )

        try:  # the cache first: even a cached model's download call would otherwise go online
            path = fetch(True)
        except Exception:
            if not allow_download:
                raise
            path = fetch(False)
        return StaticModel.from_pretrained(path)

    def embed(self, text: str) -> Vector:
        if (hit := self._cache.get(text)) is not None:
            self._cache.move_to_end(text)
            return hit
        raw = [float(x) for x in self._model.encode([text])[0]]
        norm = math.sqrt(sum(x * x for x in raw))
        vec = {i: x / norm for i, x in enumerate(raw) if x} if norm else {}
        self._cache[text] = vec
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return vec


_EMBEDDERS: dict[tuple[str, str], Embedder] = {}


def make_embedder(config: ContextGraphConfig) -> Embedder:
    """The embedder the config asks for, decided once per process.

    ``hash`` never loads a model. ``auto`` uses the model only when the extra is installed and
    the model is already downloaded (it never downloads during a turn). ``model2vec`` may
    download once. Any failure falls back to the hashed embedder.
    """
    key = (config.semantic_embedder, config.semantic_model)
    if key not in _EMBEDDERS:
        embedder: Embedder = HashEmbedder()
        if config.semantic_embedder != "hash":
            explicit = config.semantic_embedder == "model2vec"
            try:
                embedder = Model2VecEmbedder(config.semantic_model, allow_download=explicit)
            except Exception as exc:  # missing extra, no network, not downloaded, corrupt cache
                (logger.warning if explicit else logger.info)(
                    "Semantic model {} unavailable ({}: {}); using hashed words",
                    config.semantic_model, type(exc).__name__, exc,
                )
        _EMBEDDERS[key] = embedder
    return _EMBEDDERS[key]


def main(argv: list[str] | None = None) -> int:
    """``python -m nanobot.context_graph.embed [model] [--config config.json]``: download the
    model once into that config's data directory and show a similarity sample."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("model", nargs="?", default="minishlab/potion-base-8M")
    parser.add_argument("-c", "--config", type=Path, help="the instance whose data directory should hold the model")
    args = parser.parse_args(argv)
    if args.config:
        from nanobot.config.loader import set_config_path

        set_config_path(args.config)
    e = Model2VecEmbedder(args.model, allow_download=True)
    print(f"{args.model} ready in {_models_dir()}")
    print("car vs automobile:", round(cosine(e.embed("car"), e.embed("automobile")), 2))
    print("car vs banana:", round(cosine(e.embed("car"), e.embed("banana")), 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
