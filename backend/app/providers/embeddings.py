"""Provedores de embeddings.

* ``HashEmbedder`` — 100% local, sem modelo: hashing de n-gramas de caracteres
  e palavras (sem acentos). Captura semelhança lexical "difusa" (plural,
  acentuação, palavras compostas) — não é semântica profunda, mas funciona
  em qualquer máquina, instantaneamente.
* ``OllamaEmbedder`` — embeddings semânticos multilíngues locais via Ollama
  (ex.: ``paraphrase-multilingual``, ``bge-m3``, ``nomic-embed-text``).

O nome do modelo é gravado em cada trecho; trocar de modelo exige reindexar.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import httpx
import numpy as np

from app.orchestrator.textnorm import fold


class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> np.ndarray: ...


class HashEmbedder:
    def __init__(self, dim: int = 512):
        self.dim = dim
        self.name = f"hash-v1-{dim}"

    def _features(self, text: str) -> list[tuple[str, float]]:
        t = fold(text)
        words = re.findall(r"[a-z0-9]+", t)
        feats: list[tuple[str, float]] = []
        for w in words:
            feats.append(("w:" + w, 1.0))
            padded = f" {w} "
            for n in (3, 4):
                for i in range(len(padded) - n + 1):
                    feats.append(("c:" + padded[i : i + n], 0.5))
        for a, b in zip(words, words[1:], strict=False):
            feats.append(("b:" + a + "_" + b, 0.7))
        return feats

    def embed_sync(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for feat, weight in self._features(text):
                h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                sign = 1.0 if h[4] & 1 else -1.0
                out[row, idx] += sign * weight
            norm = np.linalg.norm(out[row])
            if norm > 0:
                out[row] /= norm
        return out

    async def embed(self, texts: list[str]) -> np.ndarray:
        return self.embed_sync(texts)


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.name = f"ollama:{model}"
        self.dim = 0
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> np.ndarray:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": texts})
            r.raise_for_status()
            vecs = np.asarray(r.json()["embeddings"], dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        vecs = vecs / norms
        self.dim = vecs.shape[1]
        return vecs


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
