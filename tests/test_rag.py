"""Tests for the RAG stack — embedder, vector store, retriever, knowledge base."""

import numpy as np
import pytest

from agent.embedder import HashingEmbedder
from agent.knowledge import get_knowledge_base, get_chunks_by_topic
from agent.rag import Retriever
from agent.vectorstore import VectorStore


@pytest.fixture
def embedder():
    return HashingEmbedder()


@pytest.fixture
def retriever(embedder):
    # Use the hashing embedder explicitly for deterministic, offline tests.
    return Retriever(embedder=embedder)


# --- knowledge base ---

def test_knowledge_base_nonempty():
    kb = get_knowledge_base()
    assert len(kb) >= 15
    for chunk in kb:
        assert chunk.chunk_id
        assert chunk.title
        assert chunk.topic
        assert len(chunk.body) > 50


def test_knowledge_base_unique_ids():
    kb = get_knowledge_base()
    ids = [c.chunk_id for c in kb]
    assert len(ids) == len(set(ids)), "chunk ids must be unique"


def test_knowledge_base_topics():
    """The KB must cover the key domain topics."""
    kb = get_knowledge_base()
    topics = {c.topic for c in kb}
    for expected in ["conjunction-assessment", "standards", "collision-probability",
                     "maneuver-planning", "atmosphere", "validation", "operator-runbook",
                     "sustainability"]:
        assert expected in topics, f"missing topic: {expected}"


def test_get_chunks_by_topic():
    chunks = get_chunks_by_topic("collision-probability")
    assert len(chunks) >= 1
    assert all(c.topic == "collision-probability" for c in chunks)


# --- embedder ---

def test_embedder_deterministic(embedder):
    """The hashing embedder must be deterministic (same input → same output)."""
    v1 = embedder.embed_one("collision probability and conjunction assessment")
    v2 = embedder.embed_one("collision probability and conjunction assessment")
    assert v1 == v2


def test_embedder_normalized(embedder):
    """Embeddings must be L2-normalized (unit length)."""
    v = embedder.embed_one("atmospheric drag and space weather")
    assert np.linalg.norm(v) == pytest.approx(1.0, abs=1e-6)


def test_embedder_similar_texts_closer(embedder):
    """Semantically similar texts (shared vocabulary) must be more similar."""
    v_query = embedder.embed_one("collision probability for conjunctions")
    v_related = embedder.embed_one("collision probability and the B-plane encounter")
    v_unrelated = embedder.embed_one("chocolate cake recipe with frosting")
    sim_related = np.dot(v_query, v_related)
    sim_unrelated = np.dot(v_query, v_unrelated)
    assert sim_related > sim_unrelated, "related text should be more similar"


def test_embedder_batch(embedder):
    """Batch embedding must match individual embedding."""
    texts = ["alpha beta", "gamma delta"]
    batch = embedder.embed(texts)
    assert len(batch) == 2
    assert batch[0] == embedder.embed_one("alpha beta")


# --- vector store ---

def test_vectorstore_search_returns_topk(embedder):
    store = VectorStore()
    from agent.knowledge import KnowledgeChunk

    c1 = KnowledgeChunk("a", "Collision probability", "collision-probability",
                        "The Alfriend-Foster collision probability for conjunctions.")
    c2 = KnowledgeChunk("b", "Maneuver planning", "maneuver-planning",
                        "Avoidance maneuver planning and propellant budgeting.")
    store.add(c1, embedder.embed_one(c1.as_text()))
    store.add(c2, embedder.embed_one(c2.as_text()))

    results = store.search(embedder.embed_one("collision probability"), k=1)
    assert len(results) == 1
    assert results[0].chunk.chunk_id == "a"


def test_vectorstore_empty_search():
    store = VectorStore()
    assert store.search([0.1] * 512, k=3) == []


def test_vectorstore_save_load(embedder, tmp_path):
    from agent.knowledge import KnowledgeChunk

    store = VectorStore()
    c = KnowledgeChunk("x", "Test", "test", "A test chunk about orbital mechanics.")
    store.add(c, embedder.embed_one(c.as_text()))
    path = tmp_path / "store.json"
    store.save(path)

    loaded = VectorStore()
    loaded.load(path)
    assert len(loaded) == 1
    results = loaded.search(embedder.embed_one("orbital mechanics"), k=1)
    assert results[0].chunk.chunk_id == "x"


# --- retriever ---

def test_retriever_indexes_all_chunks(retriever):
    assert len(retriever.store) == len(get_knowledge_base())


def test_retriever_collision_probability_query(retriever):
    """A collision-probability query must surface collision-probability chunks."""
    results = retriever.retrieve("How is collision probability computed?", k=3)
    assert len(results) >= 1
    topics = {r.chunk.topic for r in results}
    assert "collision-probability" in topics


def test_retriever_maneuver_query(retriever):
    """A maneuver query must surface maneuver-planning chunks."""
    results = retriever.retrieve("How do I plan a fuel-optimal avoidance maneuver?", k=3)
    topics = {r.chunk.topic for r in results}
    assert "maneuver-planning" in topics


def test_retriever_cdm_query(retriever):
    """A CDM query must surface standards chunks."""
    results = retriever.retrieve("What is a Conjunction Data Message CDM?", k=3)
    topics = {r.chunk.topic for r in results}
    assert "standards" in topics


def test_retriever_sustainability_query(retriever):
    """A sustainability query must surface sustainability chunks."""
    results = retriever.retrieve("Tell me about space debris and the Kessler syndrome", k=3)
    topics = {r.chunk.topic for r in results}
    assert "sustainability" in topics


def test_retriever_format_context_has_citations(retriever):
    """The formatted context must include chunk ids and titles (for citation)."""
    result = retriever.retrieve_and_format("collision probability", k=2)
    assert "context" in result
    assert "citations" in result
    assert result["count"] >= 1
    for cit in result["citations"]:
        assert "chunk_id" in cit
        assert "title" in cit
        assert "score" in cit
    # The context should reference the chunk ids
    for cit in result["citations"]:
        assert cit["chunk_id"] in result["context"]


def test_retriever_scores_sorted_descending(retriever):
    """Retrieved results must be sorted by descending similarity."""
    results = retriever.retrieve("atmospheric drag space weather density", k=5)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
