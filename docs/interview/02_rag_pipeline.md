# 02 — The RAG Pipeline: Ingestion, Embeddings, pgvector, Hybrid Search

> Phase 1. This is the "knowledge" half of VoxDesk: how a business's documents become answers.

---

## 1. Plain English first

A business (say, a salon) uploads a document with its prices, hours and policies. Later a customer
asks *"How much is a keratin treatment?"*. Gemini doesn't know this salon's prices — if we just
asked it, it would **make something up** (hallucinate).

**RAG (Retrieval-Augmented Generation)** fixes this in two steps:
1. **Retrieve:** find the few pieces of the salon's documents most relevant to the question.
2. **Generate:** give those pieces to the LLM and tell it to answer *only from them*, with citations.

```
INGESTION (once per document)
  upload → extract text → split into chunks → embed each chunk → store in Postgres (pgvector)

QUERY (every question)
  question → embed question → hybrid search (vector + keyword) → top 5 chunks → LLM answers with [1] citations
```

---

## 2. Ingestion step by step

**Files:** `app/api/documents.py` (upload endpoint), `app/rag/ingestion.py` (the pipeline)

### 2.1 Upload returns immediately (202 Accepted)
```python
@router.post("", status_code=202)
async def upload_document(...):
    ...validate type and size...
    document = Document(..., status=PROCESSING); commit
    background_tasks.add_task(ingest_document, document.id, data, SessionLocal, embedder)
    return document          # client gets a response right away
```
**Why 202 + background task?** Parsing and embedding can take seconds. Making the user wait on an
open HTTP request is fragile (timeouts) and wastes a server worker. Instead: respond instantly,
process in the background, and expose a `status` field (`processing → ready / failed`) the UI
can poll.

**Trade-off to mention:** FastAPI `BackgroundTasks` run in the same process. If the server restarts
mid-ingestion, the job is lost. For heavy production load you'd use a queue (Celery/Redis, which
you've used at work, or Arq). For this stage the simpler option is the right call — and you can say
exactly when you'd switch.

### 2.2 Validation
- Allowed types: PDF, TXT, Markdown. Browsers often send `.md` as `application/octet-stream`, so we
  fall back to the file extension (`resolve_content_type`). Unknown types → **415**.
- Size limit 10 MB: we read `max_bytes + 1` bytes; if we got more than the limit → **413**. This
  avoids reading a 2 GB upload into memory.

### 2.3 Text extraction
`extract_text()` uses `pypdf` for PDFs, UTF-8 decode for text. PDF parsing is **CPU-bound**, so it
runs via `run_in_threadpool` — otherwise it would block the async event loop and freeze every
other request during parsing.

### 2.4 Chunking
```python
RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
```
**Why chunk at all?** Embedding a whole document gives one blurry vector for many topics; retrieval
needs small focused pieces. Also, sending only the relevant pieces to the LLM is cheaper and faster.

**Why "recursive"?** It tries to split on paragraph breaks first, then line breaks, then sentences,
then words — so chunks stay semantically coherent instead of cutting mid-sentence.

**Why overlap (150 chars)?** If an important sentence sits on a boundary, overlap ensures it appears
whole in at least one chunk.

**Chunk-size trade-off:** smaller chunks = more precise retrieval but less context per chunk; larger
= more context but noisier matches and longer prompts. 1000 characters (~200 tokens) is a sensible
start for short business documents. *Known improvement:* markdown-header-aware splitting so each
section ("Cancellation Policy") becomes its own chunk.

### 2.5 Embedding
**File:** `app/rag/embeddings.py`

An **embedding** is a list of numbers representing meaning. Texts with similar meaning have vectors
pointing in similar directions — "can I park my car" lands near "free basement parking" even though
they share almost no words.

```python
await client.aio.models.embed_content(
    model="gemini-embedding-001",
    contents=batch,                       # up to 100 texts per request
    config=EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=768),
)
```
Decisions worth explaining:
- **`task_type`**: documents are embedded with `RETRIEVAL_DOCUMENT`, questions with
  `RETRIEVAL_QUERY`. The model optimises them differently because a question and its answer passage
  look different.
- **768 dimensions** (the model supports up to 3072): smaller vectors = smaller index, faster search,
  less storage, with minimal quality loss. Cosine distance ignores vector length, so no extra
  normalisation is needed.
- **Batching**: 100 chunks per API call instead of 100 calls.
- **`Embedder` Protocol**: the code depends on an interface (`embed_documents`, `embed_query`), not
  on Gemini. Tests plug in a `FakeEmbedder`; switching to another provider is one class.
- **Direct SDK, not LangChain** here: we wanted Gemini-specific options (`task_type`,
  `output_dimensionality`) and batching, with no LangChain features needed.

### 2.6 Storing and error handling
All chunks are inserted in one transaction, then `status = READY`. If anything fails (e.g. a scanned
PDF with no text), we **roll back**, then mark the document `FAILED` with the error message — so the
user sees *why*, and there are never half-ingested documents.

---

## 3. The data model

**File:** `app/db/models.py`

```
businesses (id, name, description)
   └── documents (id, business_id, filename, content_type, status, num_chunks, error)
          └── chunks (id, business_id, document_id, chunk_index, content,
                      embedding vector(768), tsv tsvector GENERATED)
```

Key ideas:
- **`embedding vector(768)`** — the pgvector column for semantic search.
- **`tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`** — Postgres
  builds the full-text representation automatically on insert/update. It can never drift out of sync
  with `content`.
- **`business_id` is copied onto chunks** (denormalised) so every search filters by tenant directly,
  without joining through documents.
- **`ON DELETE CASCADE`** — deleting a business deletes its documents and chunks.

---

## 4. Why pgvector instead of a dedicated vector DB

| | pgvector (VoxDesk) | Qdrant (used in FilingLens) |
|---|---|---|
| Infra | Same Postgres that already stores bookings + agent memory → one database | Separate service to run, back up, secure |
| Filtering | Plain SQL `WHERE business_id = ...`, joins with normal tables | Payload filters (good, but separate query language) |
| Consistency | Chunks and documents in one transaction | Two systems can drift out of sync |
| Scale sweet spot | Up to a few million vectors per instance | Tens/hundreds of millions, quantisation, sharding |

**Say it like this:**
> "Postgres was already the system of record for businesses, bookings and agent checkpoints, so
> pgvector let me keep vectors in the same database — one system to operate, transactional
> consistency between documents and chunks, and tenant filtering as plain SQL. I'd move to a
> dedicated vector database like Qdrant, which I used in FilingLens, if vector search became the
> dominant workload at hundreds of millions of vectors."

---

## 5. Hybrid search with RRF — the centrepiece

**File:** `app/rag/retrieval.py` (read the SQL and its comments)

### 5.1 Why two kinds of search?
| Semantic (vectors) | Keyword (full-text) |
|---|---|
| Understands meaning: "can I bring my car" ≈ "parking" | Exact terms: "keratin", "UPI", "Hydra facial" |
| Weak on rare exact terms, names, numbers | Fails on paraphrases and synonyms |

They fail in different places, so combining them is more robust than either alone.

### 5.2 The query, in plain English
One SQL query with three parts:
1. **`semantic` CTE** — top 20 chunks of *this business* ordered by cosine distance
   (`embedding <=> query_vector`), each given a rank 1..20.
2. **`keyword` CTE** — top 20 chunks of *this business* matching the full-text query, ranked by
   `ts_rank_cd`, each given a rank 1..20.
3. **Fusion** — `FULL OUTER JOIN` the two lists (a chunk may appear in one or both) and score:

```
RRF score = 1/(60 + semantic_rank) + 1/(60 + keyword_rank)     (missing rank contributes 0)
```
Return the top 5 by score.

### 5.3 Why RRF instead of adding raw scores?
Cosine distance (0–2) and `ts_rank_cd` (unbounded, depends on document length) are on **completely
different scales** — you can't add them meaningfully without fragile normalisation. RRF only uses
**ranks**, so it's scale-free, needs no tuning, and is well established (Cormack et al., 2009;
used by Elasticsearch, OpenSearch and others). `k = 60` is the standard constant; it softens the
gap between rank 1 and rank 2 so one list can't completely dominate.

### 5.4 The OR trick
`plainto_tsquery('english', 'how much is a keratin treatment')` produces
`'much' & 'keratin' & 'treatment'` — every word must match (stop-words like "how", "is", "a" are
dropped and words are stemmed). Natural questions rarely have every word in one chunk, so we
replace `&` with `|` to make it an OR query; ranking then favours chunks matching more terms.

### 5.5 Real result from our test (use this story!)
Query: *"how much is a keratin treatment"*
```
chunk 0 (hair price list)  semantic_rank=2  keyword_rank=1  → fused #1 ✅
chunk 2 (payments...)      semantic_rank=3  keyword_rank=2
chunk 1 (skin & beauty)    semantic_rank=1  keyword_rank=—
```
Semantic search alone put the wrong chunk first (the skin/beauty price list "looks" similar — it's
also a price list). The keyword "keratin" pulled the right chunk up, and RRF fused them correctly.
**That's the whole argument for hybrid search in one example.** The `/businesses/{id}/search`
debug endpoint returns both ranks so you can demonstrate this live.

### 5.6 Indexes
- **HNSW** on `embedding` with `vector_cosine_ops` — approximate nearest-neighbour search. Builds a
  multi-layer graph of vectors; search walks the graph instead of comparing against every row.
  Trade-off: slightly approximate results for big speed gains; slower inserts and more memory than
  IVFFlat, but better recall and no training step.
- **GIN** on `tsv` — inverted index (word → rows containing it), the standard index for full-text.
- **B-tree** on `business_id` — fast tenant filtering.

---

## 6. Multi-tenancy and security in retrieval

- Every retrieval query has `WHERE business_id = :business_id` in **both** CTEs — one salon can
  never retrieve another business's documents. There's a test for exactly this
  (`test_hybrid_search_is_isolated_per_business`).
- All values are **bound parameters** (`:query`, `:business_id`) — never string-formatted into SQL —
  so there's no SQL-injection risk even though the query is raw SQL.

---

## 7. Generation: grounded answers

The respond node (see `03_langgraph_agent.md`) numbers the retrieved chunks `[1]..[5]` and the
system prompt says: answer only from the context, cite like `[1]`, and if the answer isn't there,
say so and offer to connect to staff. Real test: *"Do you do tattoos?"* → *"I don't have
information about tattoo services. Would you like me to connect you with our staff?"*

---

## 8. Known limitations (say these before they ask — it shows maturity)

1. **No reranker yet.** A cross-encoder reranker (as in FilingLens) would re-score the top 20 more
   accurately. Planned with an evaluation set in Phase 5, so the improvement is *measured*.
2. **No retrieval evaluation set yet** — hit-rate/MRR measurement comes in Phase 5.
3. **Character-based chunking** — header-aware chunking would give cleaner sections.
4. **Background ingestion isn't durable** — a queue would survive restarts.
5. **No OCR** — scanned PDFs fail (gracefully, with an error message).
6. **English-only full-text config** (`'english'`) — multilingual businesses would need per-language
   configs.

---

## Q&A

**Q: What is RAG and why use it instead of fine-tuning?**
A: RAG retrieves relevant documents at query time and has the LLM answer from them. For
business facts that change (prices, hours), RAG is better: updating means re-uploading a document,
not retraining; answers can cite sources; and it works per tenant. Fine-tuning teaches style or
behaviour, not reliably fresh facts.

**Q: How do you reduce hallucinations?**
A: Ground the answer in retrieved context, instruct the model to answer only from it and cite
sources, explicitly allow "I don't know", low temperature (0.3), and later evaluate faithfulness.
The router also stops non-knowledge messages from going through retrieval at all.

**Q: Cosine similarity vs dot product vs Euclidean?**
A: Cosine compares direction only, ignoring length — standard for text embeddings. Dot product
equals cosine when vectors are normalised. Euclidean measures straight-line distance and is
sensitive to length. pgvector's `<=>` is cosine distance (1 − cosine similarity).

**Q: HNSW vs IVFFlat?**
A: HNSW: graph-based, better speed/recall trade-off, no training, but more memory and slower
builds. IVFFlat: clusters vectors into lists, needs data to train, faster to build, lower recall
unless you probe more lists. HNSW is the usual default now.

**Q: What if a question matches nothing in keyword search?**
A: The `FULL OUTER JOIN` means semantic results still come through with keyword contribution 0 —
hybrid degrades gracefully to pure semantic search.

**Q: How would you scale this to 10,000 businesses?**
A: Retrieval is already tenant-filtered and indexed. Next steps: partition `chunks` by business or
use pgvector's iterative index scans for filtered queries, move ingestion to a worker queue, cache
frequent queries in Redis, and eventually consider a dedicated vector DB if vector volume dominates.

**Q: Why store `business_id` on chunks when documents already have it?**
A: Deliberate denormalisation: the hottest query (retrieval) filters by tenant directly without a
join, and it makes tenant isolation obvious in the SQL.

**Q: Why 768 dimensions?**
A: Gemini's embedding model supports reduced dimensions with little quality loss; 768 cuts index
size and search time to a quarter of 3072, which matters for the latency budget of a voice agent.
