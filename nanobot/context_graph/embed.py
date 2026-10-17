"""Dependency-free text embedding for semantic recall.

A hashed bag-of-words: it matches shared words, not meaning. The ``Embedder`` protocol
is the seam for a real model later.
"""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from typing import Protocol

Vector = dict[int, float]

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i in is it of on or that the this to was "
    "we what which with you".split()
)


class Embedder(Protocol):
    def embed(self, text: str) -> Vector: ...


class HashEmbedder:
    """Sparse, L2-normalised term vectors. ``zlib.crc32`` keeps buckets stable across runs."""

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
