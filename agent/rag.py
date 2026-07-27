"""Retrieval-augmented generation (RAG) for the Granite analyst.

Builds a vector index over the space-domain knowledge base and retrieves the most
relevant chunks for a query, formatted with citations. The agent uses this to
answer with grounded, citable expertise — "the analyst remembers how similar
encounters were handled, and cites its sources."

The retriever is a module-level singleton (built once, reused). It uses the
watsonx embedder when available, else the deterministic hashing fallback — so
RAG always works, online or offline.
"""

from __future__ import annotations

from agent.embedder import Embedder, get_embedder
from agent.knowledge import KnowledgeChunk, get_knowledge_base
from agent.vectorstore import SearchResult, VectorStore


class Retriever:
    """Retrieves relevant knowledge chunks for a query."""

    def __init__(self, embedder: Embedder | None = None):
        self.embedder = embedder or get_embedder()
        self.store = VectorStore()
        self._build_index()

    def _build_index(self) -> None:
        """Embed and index every chunk in the knowledge base."""
        chunks = get_knowledge_base()
        texts = [c.as_text() for c in chunks]
        vectors = self.embedder.embed(texts)
        for chunk, vector in zip(chunks, vectors):
            self.store.add(chunk, vector)

    def retrieve(self, query: str, k: int = 3) -> list[SearchResult]:
        """Return the top-k most relevant knowledge chunks for a query."""
        query_vector = self.embedder.embed([query])[0]
        return self.store.search(query_vector, k=k)

    def format_context(self, results: list[SearchResult]) -> str:
        """Format retrieved chunks as cited context for the agent prompt."""
        if not results:
            return "(No relevant knowledge found.)"
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"[{i}] {r.chunk.title} (topic: {r.chunk.topic}, id: {r.chunk.chunk_id}, "
                f"relevance: {r.score:.2f})\n{r.chunk.body}"
            )
        return "\n\n".join(parts)

    def retrieve_and_format(self, query: str, k: int = 3) -> dict:
        """Retrieve top-k chunks and return both the formatted context and the citations."""
        results = self.retrieve(query, k=k)
        return {
            "query": query,
            "context": self.format_context(results),
            "citations": [
                {
                    "chunk_id": r.chunk.chunk_id,
                    "title": r.chunk.title,
                    "topic": r.chunk.topic,
                    "score": round(r.score, 3),
                }
                for r in results
            ],
            "count": len(results),
        }


# Module-level singleton — built once, reused across agent calls.
_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    """Return the shared Retriever instance (built on first call)."""
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
