"""Local CPU embeddings for the semantic cache (never a generative model).

`FastEmbedder` lazily loads `BAAI/bge-small-en-v1.5` (384-dim ONNX, ~80 MB) on
first real use; unit tests inject `DeterministicTestEmbedder` (no downloads).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import threading
from pathlib import Path
from typing import Any, Protocol

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
CACHE_DIR_ENV = "AUTOMATED_APPLY_EMBED_CACHE_DIR"
DEFAULT_CACHE_DIR = Path.home() / "Library/Application Support/automated-apply/fastembed"


class Embedder(Protocol):
    model_name: str
    dimensions: int

    @property
    def ready(self) -> bool: ...

    async def embed(self, text: str) -> list[float]: ...


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else vector


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class FastEmbedder:
    """Process-wide lazy singleton around fastembed's ONNX TextEmbedding (CPU only)."""

    _model: Any = None
    _lock = threading.Lock()

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: str | os.PathLike[str] | None = None) -> None:
        self.model_name = model_name
        self.dimensions = DIMENSIONS
        self.cache_dir = Path(cache_dir or os.environ.get(CACHE_DIR_ENV) or DEFAULT_CACHE_DIR).expanduser()

    @property
    def ready(self) -> bool:
        return type(self)._model is not None

    def downloaded(self) -> bool:
        """Model files already on disk (first use will not download)."""
        return self.cache_dir.is_dir() and any(self.cache_dir.rglob("*.onnx"))

    def _load(self) -> Any:
        cls = type(self)
        with cls._lock:
            if cls._model is None:
                from fastembed import TextEmbedding

                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cls._model = TextEmbedding(model_name=self.model_name, cache_dir=str(self.cache_dir),
                                           threads=1)
            return cls._model

    def _embed_sync(self, text: str) -> list[float]:
        model = self._load()
        vector = next(iter(model.embed([text])))
        return l2_normalize([float(x) for x in vector])

    async def embed(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)


class DeterministicTestEmbedder:
    """Offline bag-of-words hashing embedder with the same 384-dim contract (tests only)."""

    model_name = "deterministic-test-embedder"
    dimensions = DIMENSIONS
    ready = True

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[a-z0-9+#]+", text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        return l2_normalize(vector)
