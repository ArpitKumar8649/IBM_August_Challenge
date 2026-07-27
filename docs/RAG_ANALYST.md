# Retrieval-Augmented Analyst (RAG)

> The Granite analyst doesn't just compute — it **remembers and cites.** A
> vector-database memory of space-domain knowledge lets it answer with grounded,
> citable expertise instead of generic prose.
>
> RAG (retrieval-augmented generation) is one of the challenge's *encouraged
> technologies* (vector databases). This document covers the architecture, the
> knowledge base, the embedding strategy, and how it integrates with the agent.

---

## Why RAG

The base agent (Phases 1–3) is a strict tool-caller: it gets numbers from the
engine and composes prose. But an operator also asks *"why?"* and *"how is this
normally handled?"* — questions of **domain expertise**, not computation. Without
grounding, an LLM answers those from its training data, which can be vague or
wrong.

RAG fixes this: the analyst retrieves the most relevant chunks from a curated
space-domain knowledge base and answers **with citations** ("per the operator
runbook [ops-001], re-screen within 24 h of TCA…"). This makes the analyst:

- **Grounded** — answers draw on verified domain content, not hallucination.
- **Citable** — every claim traces to a knowledge chunk the operator can inspect.
- **Maintainable** — updating the knowledge base updates the analyst's expertise,
  no retraining.

It complements the validation layer: the validator checks *numbers*; RAG grounds
*explanations*.

---

## Architecture

```
operator question
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  query_knowledge_base tool (the agent's RAG entry point)      │
│                                                               │
│   query ──► Embedder ──► query vector                         │
│                              │                                │
│                              ▼                                │
│                     VectorStore.search (cosine similarity)    │
│                              │                                │
│                              ▼                                │
│                     top-k KnowledgeChunks + scores            │
│                              │                                │
│                              ▼                                │
│                     formatted context + citations             │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
   agent composes a grounded, cited answer
```

### Components

| Component | File | Role |
|-----------|------|------|
| Knowledge base | `agent/knowledge.py` | 18 curated chunks across 8 topics, each with id/title/topic/body |
| Embedder | `agent/embedder.py` | `WatsonxEmbedder` (granite-embedding) + `HashingEmbedder` (offline fallback) |
| Vector store | `agent/vectorstore.py` | Cosine-similarity search + JSON persistence (pgvector-ready schema) |
| Retriever | `agent/rag.py` | Builds the index, retrieves top-k, formats cited context |
| Agent tool | `agent/tools.py` | `query_knowledge_base(query, k)` — the agent's RAG entry point |

---

## The knowledge base

18 chunks across 8 topics, each a self-contained unit of expertise:

| Topic | Chunks | Covers |
|-------|--------|--------|
| `conjunction-assessment` | ca-001, ca-002 | The screening workflow; thresholds and triage |
| `standards` | cdm-001, cdm-002 | CDM (CCSDS 508.0-B-1); ODM/OMM (CCSDS 502.0-B-2) |
| `collision-probability` | pc-001, pc-002 | Alfriend–Foster 2-D Pc; covariance realism & dilution |
| `maneuver-planning` | man-001, man-002, man-003 | Avoidance planning; CW fuel-optimal; rocket equation |
| `atmosphere` | drag-001, drag-002 | NRLMSISE-00 drag; why TLEs go stale |
| `validation` | val-001 | OrbitWarden's validation results |
| `operator-runbook` | ops-001, ops-002 | Responding to a conjunction; human-in-the-loop |
| `sustainability` | sus-001, sus-002 | Kessler syndrome; democratizing SSA |
| `geometry` | geo-001 | The RSW frame and encounter geometry |
| `ibm-stack` | ibm-001 | OrbitWarden's IBM technology stack |

Each chunk is written to be **retrievable and citable** — a clear title, a topic
tag, and a self-contained body that answers a class of operator questions.

---

## Embedding strategy

### Production: watsonx.ai semantic embeddings
`WatsonxEmbedder` calls the watsonx.ai text-embeddings API with
`ibm/granite-embedding-278m-multilingual` (an available watsonx model, 384-dim).
This gives true **semantic** similarity — "how do I avoid a collision?" matches
"avoidance maneuver planning" even without shared keywords.

### Offline fallback: feature-hashing embedder
`HashingEmbedder` is a deterministic, dependency-free fallback using the
**hashing trick**: it maps tokens and bigrams into a fixed 512-dim vector (with
sign hashing to reduce collision bias), then L2-normalizes. Texts sharing domain
vocabulary have high cosine similarity.

This is a legitimate **sparse-retrieval** method, and it works well here because
the knowledge base is a *curated domain corpus* where queries and chunks share
terminology ("collision probability," "maneuver," "CDM"). It guarantees RAG works
even with no network or credentials — important for tests and offline demos.

`get_embedder()` returns the watsonx embedder when it's available and working
(smoke-tested), else the hashing fallback.

---

## The vector store

`VectorStore` is an in-memory store with:
- **Cosine-similarity search** (unit-normalized vectors → similarity = dot product).
- **JSON persistence** (`save`/`load`) so the index can be cached.
- A **logical schema** (id, content, embedding, metadata) that mirrors a
  **pgvector** table — swapping to Postgres+pgvector later means translating only
  the `add`/`search` methods; the rest of the RAG layer is unchanged.

---

## Integration with the agent

The agent calls `query_knowledge_base(query, k)` like any other tool. The system
prompt instructs it to:
- Use the knowledge base to ground explanations and **cite the chunk id**.
- Combine retrieved knowledge with tool-computed numbers.

Example flow:
> **Operator:** "Why does the storm flag matter for my conjunction?"
> **Agent:** calls `query_knowledge_base("storm flag atmospheric drag TLE staleness")`
> → retrieves drag-001, drag-002 → answers: *"During a geomagnetic storm the
> thermosphere expands and LEO density rises ~1.7×, increasing drag and making
> TLE predictions diverge [drag-001]. That's why we recommend re-screening within
> 24 h of TCA when the storm flag is set [drag-002]."*

---

## Verified behavior (18 tests)

- Knowledge base: non-empty, unique ids, covers all 8 key topics.
- Embedder: deterministic, L2-normalized, similar texts closer than unrelated,
  batch matches individual.
- Vector store: top-k retrieval, empty-store safety, save/load round-trip.
- Retriever: indexes all chunks; collision-probability / maneuver / CDM /
  sustainability queries surface the right topics; context includes citations;
  results sorted by descending similarity.

---

## Honest scope & future work

- The hashing fallback is **keyword-overlap** retrieval, not true semantics —
  the watsonx embedder is the production path. For the curated domain corpus the
  fallback is effective, but semantic matching is strictly better for paraphrased
  queries.
- The knowledge base is **curated and static** — a strength (verified content) and
  a limitation (must be updated manually). Future: ingest live CDM archives,
  operator transcripts, and ADS literature for a growing memory.
- **pgvector** (already in the Postgres plan) would scale the store and enable
  hybrid (dense + keyword) retrieval.

---

## References

- Lewis et al. (2020), "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"
- Weinberger et al. (2009), "Feature Hashing for Large Scale Multitask Learning" (the hashing trick)
- IBM Granite embeddings (`ibm/granite-embedding-278m-multilingual`) on watsonx.ai
- pgvector — vector similarity search for Postgres

---

*Added 2026-07-24. 18 RAG tests; 183 total across the system. The agent contract
is now 11 tools. Run: `pytest tests/test_rag.py`.*
