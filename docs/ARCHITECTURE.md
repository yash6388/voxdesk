# VoxDesk — Architecture

> Living document — updated after every phase. Diagrams are [Mermaid](https://mermaid.js.org/):
> GitHub renders them automatically, and draw.io can import them (see the last section).
>
> **Status:** Phase 1 built (text chat + RAG). Components from later phases are marked *planned*.

---

## 1. System overview (target architecture)

What VoxDesk looks like when all phases are done. Solid = built, dashed = planned.

```mermaid
flowchart LR
    customer(["Customer<br/>browser chat / voice"])
    owner(["Business owner<br/>dashboard"])

    subgraph FE["Frontend · Next.js"]
        ui["Chat + voice UI<br/>Knowledge base<br/>Dashboard"]
    end

    subgraph BE["Backend · FastAPI"]
        api["REST + SSE API"]
        voice["Voice pipeline<br/>STT / TTS"]
        sup["LangGraph supervisor<br/>route · retrieve · respond"]
    end

    subgraph AG["Specialist agents · A2A"]
        ka["Knowledge agent<br/>RAG"]
        ba["Booking agent"]
    end

    mcp["VoxDesk MCP server<br/>booking tools"]

    subgraph DATA["Data"]
        pg[("PostgreSQL 16 + pgvector<br/>businesses · documents · chunks<br/>bookings · checkpoints")]
        redis[("Redis<br/>cache · rate limits")]
    end

    gemini["Google Gemini API<br/>chat · embeddings"]

    customer --> ui
    owner --> ui
    ui -- "HTTP / SSE" --> api
    ui -. "WebSocket audio" .-> voice
    voice -.-> sup
    api --> sup
    sup --> pg
    sup --> gemini
    sup -. "A2A" .-> ka
    sup -. "A2A" .-> ba
    ba -. "MCP" .-> mcp
    mcp -.-> pg
    ka -.-> pg
    api -.-> redis

    classDef planned stroke-dasharray: 5 5
    class voice,ka,ba,mcp,redis planned
```

| Component | Responsibility | Tech | Status |
|---|---|---|---|
| Frontend | Landing page; dashboard: businesses, knowledge base, playground with agent inspector (later bookings, voice, analytics) | Next.js, TypeScript, Tailwind, Lucide | ✅ Phase 1 |
| API | REST endpoints, SSE streaming, validation, (later) auth | FastAPI, Pydantic | ✅ Phase 1 |
| Supervisor | Classifies intent, rewrites queries, orchestrates steps, keeps memory | LangGraph, Gemini | ✅ Phase 1 (becomes A2A client in Phase 3) |
| RAG | Ingestion + hybrid retrieval | pgvector, Postgres full-text, Gemini embeddings | ✅ Phase 1 (moves into knowledge agent in Phase 3) |
| MCP server | Booking tools usable by any MCP client | FastMCP | ⏳ Phase 2 |
| A2A agents | Independent knowledge + booking services | a2a-sdk | ⏳ Phase 3 |
| Voice | Speech in → agent → speech out | WebSocket, STT/TTS (TBD) | ⏳ Phase 4 |
| PostgreSQL | System of record + vectors + agent checkpoints | Postgres 16 + pgvector | ✅ |
| Redis | Cache, rate limiting, pub/sub | Redis 7 | Running, used from Phase 5 |

---

## 2. Current deployment (Phase 1, local)

```mermaid
flowchart TB
    browser(["Browser"])
    subgraph host["Developer machine"]
        next["Next.js dev server<br/>:3000"]
        fastapi["FastAPI · uvicorn<br/>:8000"]
        subgraph docker["Docker Compose"]
            pg[("pgvector/pgvector:pg16<br/>host :5433")]
            redis[("redis:7-alpine<br/>host :6380")]
        end
    end
    gemini["Gemini API<br/>generativelanguage.googleapis.com"]

    browser --> next
    browser -- "fetch / SSE<br/>CORS" --> fastapi
    fastapi -- "asyncpg: app data<br/>psycopg: checkpoints" --> pg
    fastapi -- "HTTPS" --> gemini
```

---

## 3. Backend components (Phase 1)

```mermaid
flowchart TB
    subgraph api["app/api"]
        bus["businesses.py<br/>CRUD + /search"]
        docs["documents.py<br/>upload · list · delete"]
        chat["chat.py<br/>SSE stream · history"]
    end
    subgraph rag["app/rag"]
        ing["ingestion.py<br/>parse · chunk · embed · store"]
        ret["retrieval.py<br/>hybrid search + RRF"]
        emb["embeddings.py<br/>Embedder protocol · Gemini"]
    end
    subgraph graph["app/graph"]
        builder["builder.py<br/>route → retrieve → respond"]
    end
    subgraph db["app/db"]
        models["models.py"]
        session["session.py<br/>async engine"]
    end
    ckpt["AsyncPostgresSaver<br/>checkpointer"]

    docs -- "BackgroundTasks" --> ing
    bus --> ret
    chat --> builder
    builder --> ret
    builder --> ckpt
    ing --> emb
    ret --> emb
    ing --> session
    ret --> session
```

---

## 4. Agent graph (LangGraph)

```mermaid
flowchart LR
    S((START)) --> route["route<br/>flash-lite · structured output<br/>intent + standalone query"]
    route -- knowledge --> retrieve["retrieve<br/>hybrid search · top 5"]
    route -- smalltalk --> respond["respond<br/>flash · grounded · cites [n]"]
    route -- booking --> booking["booking<br/>placeholder until Phase 2"]
    retrieve --> respond
    respond --> E((END))
    booking --> E
```

State is checkpointed to Postgres after every node, keyed by `{business_id}:{thread_id}`.

---

## 5. Request flows

### 5.1 Chat message (streaming)

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as FastAPI /chat
    participant G as LangGraph
    participant C as Checkpointer (Postgres)
    participant R as Hybrid search (Postgres)
    participant L as Gemini

    B->>A: POST /chat {business_id, message, thread_id}
    A-->>B: SSE meta {thread_id}
    A->>G: astream(inputs, thread)
    G->>C: load previous state
    G->>L: route (structured output)
    L-->>G: intent=knowledge, query="keratin treatment cost"
    A-->>B: SSE route
    G->>L: embed query
    G->>R: vector + full-text, RRF fusion
    R-->>G: top 5 chunks
    A-->>B: SSE sources
    G->>L: generate answer from context
    loop as tokens arrive
        L-->>G: token
        A-->>B: SSE token
    end
    G->>C: save state (after each node)
    A-->>B: SSE done
```

### 5.2 Document ingestion

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as FastAPI
    participant BG as Background task
    participant L as Gemini embeddings
    participant P as Postgres

    B->>A: POST /businesses/{id}/documents (file)
    A->>A: validate type (415) and size (413)
    A->>P: insert document (status=processing)
    A-->>B: 202 Accepted
    A->>BG: ingest_document()
    BG->>BG: extract text (threadpool) · split into chunks
    BG->>L: embed chunks (batches of 100)
    L-->>BG: 768-d vectors
    BG->>P: insert chunks, status=ready (one transaction)
    loop every 2s while processing
        B->>A: GET documents
        A-->>B: status
    end
```

---

## 6. Data model

```mermaid
erDiagram
    BUSINESSES ||--o{ DOCUMENTS : has
    BUSINESSES ||--o{ CHUNKS : "owns (tenant filter)"
    DOCUMENTS ||--o{ CHUNKS : "split into"

    BUSINESSES {
        uuid id PK
        string name
        text description
        timestamptz created_at
    }
    DOCUMENTS {
        uuid id PK
        uuid business_id FK
        string filename
        string content_type
        enum status "processing | ready | failed"
        int num_chunks
        text error
        timestamptz created_at
    }
    CHUNKS {
        uuid id PK
        uuid business_id FK
        uuid document_id FK
        int chunk_index
        text content
        vector embedding "768-d, HNSW cosine"
        tsvector tsv "generated, GIN"
        timestamptz created_at
    }
```

LangGraph's checkpoint tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`,
`checkpoint_migrations`) live in the same database and are managed by LangGraph, not Alembic.

---

## 7. Key design decisions

Full list with dates in [`PROGRESS.md`](PROGRESS.md#decision-log); explanations in
[`interview/`](interview/00_INDEX.md).

| Decision | Why |
|---|---|
| Explicit LangGraph state machine (not a free agent loop) | Predictable, testable control flow; checkpointing, streaming, interrupts built in |
| pgvector in the main Postgres | One database for app data, vectors and agent memory; SQL tenant filtering |
| Hybrid search fused with RRF | Semantic + keyword fail differently; RRF merges ranks without score normalisation |
| Router does intent + query rewrite in one call | Fewer LLM calls (latency matters for voice); follow-ups retrieve correctly |
| SSE for chat, WebSocket for voice (planned) | One-way token stream vs two-way audio stream |
| `{business_id}:{thread_id}` checkpoint keys | Tenant isolation for conversations |
| Background ingestion with 202 | Fast API responses; status polled by UI |

---

## 8. Drawing this in draw.io (or Excalidraw / Lucidchart)

**Fastest: import the Mermaid code**
1. Open [app.diagrams.net](https://app.diagrams.net) → blank diagram.
2. **Arrange → Insert → Advanced → Mermaid…**
3. Paste a diagram's code (everything between ` ```mermaid ` and ` ``` `) → **Insert**.
4. The result is editable shapes — drag to tidy the layout, recolour, add icons.
5. Save as `docs/diagrams/voxdesk-architecture.drawio` and export a PNG for the README.

**Drawing by hand (e.g. live in an interview)** — use the System overview (section 1) and keep
this left-to-right order, which matches how a request flows:

1. **Clients** — customer (chat/voice), business owner.
2. **Frontend** — Next.js.
3. **API layer** — FastAPI (REST + SSE, later WebSocket for voice).
4. **Orchestration** — LangGraph supervisor (draw the route → retrieve → respond mini-graph inside).
5. **Agents & tools** — knowledge agent, booking agent (A2A), MCP server (booking tools).
6. **Data** — Postgres + pgvector (one cylinder, list what it stores), Redis.
7. **External** — Gemini API (a cloud shape on the edge).

Conventions that make it read well: data stores as cylinders, external services as clouds, label
every arrow with the protocol (**HTTP/SSE, WebSocket, A2A, MCP, SQL**), dashed lines for async or
planned paths, and one colour per layer.
