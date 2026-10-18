"""Passage and query embeddings. Default model is intfloat/multilingual-e5-small."""
from __future__ import annotations

import hashlib
import math
from typing import Protocol

from .config import settings
from .llm import embed_api

_local_model = None


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class HashEmbedder:
    """Deterministic stand-in used by tests. Not for real retrieval quality."""

    def _vec(self, text: str) -> list[float]:
        out: list[float] = []
        seed = text.encode("utf-8")
        counter = 0
        dim = settings.embedding_dim
        while len(out) < dim:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "little")).digest()
            counter += 1
            for i in range(0, len(digest), 4):
                n = int.from_bytes(digest[i:i + 4], "little")
                out.append((n / 2**32) * 2 - 1)
                if len(out) == dim:
                    break
        return _normalize(out)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec("passage: " + t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec("query: " + text)


class LocalEmbedder:
    def __init__(self):
        global _local_model
        if _local_model is None:
            from sentence_transformers import SentenceTransformer
            _local_model = SentenceTransformer(settings.embedding_model)
        self.model = _local_model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        arr = self.model.encode(
            [f"passage: {t}" for t in texts], normalize_embeddings=True, show_progress_bar=False
        )
        return [row.tolist() for row in arr]

    def embed_query(self, text: str) -> list[float]:
        arr = self.model.encode(f"query: {text}", normalize_embeddings=True, show_progress_bar=False)
        return arr.tolist()


class ApiEmbedder:
    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return embed_api([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return embed_api([f"query: {text}"])[0]


def get_embedder() -> Embedder:
    provider = settings.embedding_provider
    if provider == "hash":
        return HashEmbedder()
    if provider == "api":
        return ApiEmbedder()
    return LocalEmbedder()
