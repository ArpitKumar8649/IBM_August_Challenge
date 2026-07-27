"""Vector store for the retrieval-augmented analyst.

A lightweight in-memory vector store with cosine-similarity search and JSON
persistence. The logical schema (id, content, embedding, metadata) mirrors a
pgvector table, so swapping to Postgres+pgvector later is a matter of translating
the two query methods — the rest of the RAG layer is unchanged.

This is the "vector database" (an encouraged technology) that gives the analyst
its long-term memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from agent.knowledge import KnowledgeChunk


@dataclass
class SearchResult:
    """A retrieved knowledge chunk with its similarity score."""

    chunk: KnowledgeChunk
    score: float  # cosine similarity in [-1, 1]


class VectorStore:
    """In-memory vector store with cosine-similarity search."""

    def __init__(self):
        self._chunks: list[KnowledgeChunk] = []
        self._vectors: list[np.ndarray] = []

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunk: KnowledgeChunk, vector: list[float] | np.ndarray) -> None:
        """Add a chunk with its embedding vector."""
        vec = np.asarray(vector, dtype=np.float64)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm  # store unit vectors → cosine sim = dot product
        self._chunks.append(chunk)
        self._vectors.append(vec)

    def search(self, query_vector: list[float] | np.ndarray, k: int = 3) -> list[SearchResult]:
        """Return the top-k most similar chunks to the query vector."""
        if not self._chunks:
            return []
        q = np.asarray(query_vector, dtype=np.float64)
        q_norm = np.linalg.norm(q)
        if q_norm > 0:
            q = q / q_norm
        # Cosine similarity = dot product of unit vectors.
        matrix = np.vstack(self._vectors)
        scores = matrix @ q
        top_idx = np.argsort(scores)[::-1][:k]
        return [
            SearchResult(chunk=self._chunks[i], score=float(scores[i]))
            for i in top_idx
            if scores[i] > 0  # only return positively-similar chunks
        ]

    def save(self, path: str | Path) -> None:
        """Persist the store to JSON (chunk metadata + vectors)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "title": c.title,
                    "topic": c.topic,
                    "body": c.body,
                    "vector": v.tolist(),
                }
                for c, v in zip(self._chunks, self._vectors)
            ]
        }
        path.write_text(json.dumps(data))

    def load(self, path: str | Path) -> None:
        """Load the store from JSON."""
        path = Path(path)
        data = json.loads(path.read_text())
        self._chunks = []
        self._vectors = []
        for item in data["chunks"]:
            chunk = KnowledgeChunk(
                chunk_id=item["chunk_id"],
                title=item["title"],
                topic=item["topic"],
                body=item["body"],
            )
            self.add(chunk, item["vector"])
