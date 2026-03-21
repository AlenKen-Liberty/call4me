from __future__ import annotations

import hashlib
import re

import numpy as np


class MemoryEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dim: int = 256):
        self.model_name = model_name
        self.dim = dim
        self._backend = None

        try:
            from fastembed import TextEmbedding
        except ImportError:
            return

        self._backend = TextEmbedding(model_name)

    def embed(self, text: str) -> np.ndarray:
        if self._backend is not None:
            embedding = list(self._backend.embed([text]))[0]
            return np.asarray(embedding, dtype=np.float32)

        vector = np.zeros(self.dim, dtype=np.float32)
        tokens = self._tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            idx = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vector[idx] += 1.0

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9_]+", text.casefold())
