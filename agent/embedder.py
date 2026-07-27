"""Embeddings for the retrieval-augmented analyst.

Two backends:
  · WatsonxEmbedder — production semantic embeddings via watsonx.ai
    (ibm/granite-embedding-278m-multilingual, an available watsonx model).
  · HashingEmbedder — a deterministic, dependency-free fallback using feature
    hashing (the "hashing trick"). It maps token (and bigram) overlaps into a
    fixed-size vector, so texts sharing domain vocabulary have high cosine
    similarity. This is a legitimate sparse-retrieval method and works well for
    a curated domain knowledge base where queries and chunks share terminology.

`get_embedder()` returns the watsonx embedder when credentials are available and
working, else the hashing fallback — so the RAG analyst always works.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

import httpx

IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
DEFAULT_EMBED_MODEL = "ibm/granite-embedding-278m-multilingual"
HASH_DIM = 512

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _load_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _tokenize(text: str) -> list[str]:
    """Lowercase tokens plus bigrams (for phrase discrimination)."""
    unigrams = _TOKEN_RE.findall(text.lower())
    bigrams = [f"{unigrams[i]}_{unigrams[i + 1]}" for i in range(len(unigrams) - 1)]
    return unigrams + bigrams


class Embedder:
    """Base class — embed a list of texts into a list of vectors."""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashingEmbedder(Embedder):
    """Deterministic feature-hashing embedder (offline fallback)."""

    def __init__(self, dim: int = HASH_DIM):
        self.dim = dim

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokenize(text):
            # Hash to a bucket; use a second hash for the sign (reduces collision bias).
            h = int(hashlib.md5(token.encode()).hexdigest(), 16)
            bucket = h % self.dim
            sign = 1.0 if (h // self.dim) % 2 == 0 else -1.0
            vec[bucket] += sign
        # L2-normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class WatsonxEmbedder(Embedder):
    """Semantic embeddings via the watsonx.ai text-embeddings REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
        region: str | None = None,
        model_id: str | None = None,
    ):
        _load_env()
        self.api_key = api_key or os.environ.get("WATSONX_APIKEY", "")
        self.project_id = project_id or os.environ.get("WATSONX_PROJECT_ID", "")
        self.region = region or os.environ.get("WATSONX_REGION", "us-south")
        self.model_id = model_id or os.environ.get("WATSONX_EMBED_MODEL_ID", DEFAULT_EMBED_MODEL)
        self.dim = 384  # granite-embedding-278m output dim
        self._token: str | None = None

    def _get_token(self, client: httpx.Client) -> str:
        if self._token:
            return self._token
        resp = client.post(
            IAM_TOKEN_URL,
            data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": self.api_key},
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key or not self.project_id:
            raise RuntimeError("watsonx credentials not configured")
        url = f"https://{self.region}.ml.cloud.ibm.com/ml/v1/text/embeddings?version=2024-03-14"
        with httpx.Client(timeout=60.0) as client:
            token = self._get_token(client)
            resp = client.post(
                url,
                json={
                    "model_id": self.model_id,
                    "project_id": self.project_id,
                    "inputs": texts,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [r["embedding"] for r in data["results"]]


def get_embedder(prefer_watsonx: bool = True) -> Embedder:
    """Return the watsonx embedder if available and working, else the hashing fallback."""
    if prefer_watsonx:
        try:
            embedder = WatsonxEmbedder()
            # Smoke test with a tiny embedding call.
            embedder.embed(["test"])
            return embedder
        except Exception:  # noqa: BLE001 — any failure → fallback
            pass
    return HashingEmbedder()
