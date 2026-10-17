# VoxDesk — Architecture

> Living document — updated after every phase. Diagrams are [Mermaid](https://mermaid.js.org/):
> GitHub renders them automatically, and draw.io can import them (see the last section).
>
> **Status:** Phase 2 built (text chat + RAG + MCP booking with human-in-the-loop).
> Components from later phases are marked *planned*.

---

## 1. System overview (target architecture)

Solid = built, dashed = planned.

```mermaid
flowchart LR
    customer(["Customer<br/>browser chat / voice"])
    owner(["Business owner<br/>dashboard"])

    subgraph FE["Frontend · Next.js"]
        ui["Landing · Dashboard<br/>Playground · Knowledge<br/>Services · Bookings"]
    end

    subgraph BE["Backend · FastAPI"]
        api["REST + SSE API"]
        voice["Voice pipeline<br/>STT / TTS"]
        sup["LangGraph supervisor<br/>route · retrieve · respond<br/>booking agent · confirm"]
    end

    subgraph AG["Specialist agents · A2A"]
        ka["Knowledge agent"]
        ba["Booking agent"]
    end

    mcp["VoxDesk MCP server :8001<br/>7 booking tools"]

    subgraph DATA["Data"]
        pg[("PostgreSQL 16 + pgvector<br/>businesses · documents · chunks<br/>services · hours · bookings<br/>checkpoints")]
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
    sup -- "MCP · Streamable HTTP" --> mcp
    mcp --> pg
    sup -. "A2A" .-> ka
    sup -. "A2A" .-> ba
    api -.-> redis

    classDef planned stroke-dasharray: 5 5
    class voice,ka,ba,redis planned
```

| Component | Responsibility | Tech | Status |
|---|---|---|---|
| Frontend | Landing page; dashboard: businesses, knowledge base, services & hours, bookings, playground with agent inspector + confirmation card | Next.js, TypeScript, Tailwind, Lucide | ✅ Phase 1–2 |
| API | REST (businesses, documents, services, hours, bookings), SSE chat + resume | FastAPI, Pydantic | ✅ Phase 1–2 |
| Supervisor graph | Routes intent, rewrites queries, RAG, booking agent loop, human-in-the-loop, memory | LangGraph, Gemini | ✅ Phase 1–2 (agents split out via A2A in Phase 3) |
| RAG | Ingestion + hybrid retrieval | pgvector, Postgres full-text, Gemini embeddings | ✅ Phase 1 |
| MCP server | Booking tools usable by any MCP client; auth + tenant headers | FastMCP (`mcp` SDK), Streamable HTTP | ✅ Phase 2 |
| Booking domain | Availability, validation, booking rules shared by MCP + REST | SQLAlchemy, Postgres exclusion constraint | ✅ Phase 2 |
| A2A agents | Independent knowledge + booking services | a2a-sdk | ⏳ Phase 3 |
| Voice | Speech in → agent → speech out | WebSocket, STT/TTS (TBD) | ⏳ Phase 4 |
| PostgreSQL | System of record + vectors + agent checkpoints | Postgres 16 + pgvector + btree_gist | ✅ |
| Redis | Cache, rate limiting, pub/sub | Redis 7 | Running, used from Phase 5 |

---

## 2. Current deployment (Phase 2, local)

```mermaid
flowchart TB
    browser(["Browser"])
    inspector(["Any MCP client<br/>MCP Inspector · Claude Desktop"])
    subgraph host["Developer machine"]
        next["Next.js dev server<br/>:3000"]
        fastapi["FastAPI · uvicorn<br/>:8000"]
        mcpserver["VoxDesk MCP server<br/>uvicorn :8001"]
        subgraph docker["Docker Compose"]
            pg[("pgvector/pgvector:pg16<br/>host :5433")]
            redis[("redis:7-alpine<br/>host :6380")]
        end
    end
    gemini["Gemini API"]

    browser --> next
    browser -- "fetch / SSE · CORS" --> fastapi
    fastapi -- "MCP · Bearer key + X-Business-Id" --> mcpserver
    inspector -. "MCP" .-> mcpserver
    fastapi -- "asyncpg: app data<br/>psycopg: checkpoints" --> pg
    mcpserver -- "asyncpg" --> pg
    fastapi -- "HTTPS" --> gemini
```

Processes to run locally: `docker compose up -d`, the API (`uvicorn app.main:app`), the MCP server
(`python -m app.mcp.server`) and the frontend (`npm run dev`).

---

## 3. Backend components

```mermaid
flowchart TB
    subgraph api["app/api"]
        bus["businesses.py<br/>CRUD + /search"]
        docs["documents.py<br/>upload · list · delete"]
        bk["booking.py<br/>services · hours · bookings"]
        chat["chat.py<br/>SSE stream · resume · history"]
    end
    subgraph graph["app/graph"]
        builder["builder.py<br/>route · retrieve · respond<br/>booking_agent · confirm · tools"]
        tools["tools.py<br/>MCPToolProvider"]
    end
    subgraph mcp["app/mcp (separate process)"]
        server["server.py<br/>FastMCP · 7 tools · auth middleware"]
    end
    subgraph domain["app/booking"]
        svc["service.py<br/>availability · rules · writes"]
    end
    subgraph rag["app/rag"]
        ing["ingestion.py"]
        ret["retrieval.py<br/>hybrid + RRF"]
        emb["embeddings.py"]
    end
    db[("app/db<br/>models · session")]
    ckpt["AsyncPostgresSaver"]

    chat --> builder
    builder --> ret
    builder --> tools
    tools -- "MCP over HTTP" --> server
    server --> svc
    bk --> svc
    builder --> ckpt
    docs --> ing
    ing --> emb
    ret --> emb
    svc --> db
    ing --> db
    ret --> db
```

The booking rules live once in `app/booking/service.py` and are used by both the MCP server
(customers, via the agent) and the owner REST API.

---

## 4. Agent graph (LangGraph)

```mermaid
flowchart LR
    S((START)) --> route["route<br/>flash-lite · structured output<br/>intent + standalone query"]
    route -- knowledge --> retrieve["retrieve<br/>hybrid search · top 5"]
    route -- smalltalk --> respond["respond<br/>grounded · cites [n]"]
    route -- booking --> agent["booking_agent<br/>LLM + MCP tools"]
    retrieve --> respond
    respond --> E((END))
    agent -- "no tool calls" --> E
    agent -- "read tools" --> tools["tools<br/>call MCP"]
    agent -- "write tools" --> confirm{{"confirm<br/>validate + guardrail<br/>⏸ interrupt"}}
    confirm -- approved --> tools
    confirm -- "declined / invalid" --> agent
    tools --> agent
```

State is checkpointed to Postgres after every node, keyed by `{business_id}:{thread_id}`, which is
what lets `confirm` pause and resume in a later HTTP request.

---

## 5. Request flows

### 5.1 Knowledge question (streaming)

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as FastAPI /chat
    participant G as LangGraph
    participant R as Hybrid search
    participant L as Gemini

    B->>A: POST /chat {business_id, message, thread_id}
    A-->>B: SSE meta
    A->>G: astream(inputs)
    G->>L: route (structured output)
    A-->>B: SSE route
    G->>R: vector + full-text, RRF
    A-->>B: SSE sources
    G->>L: answer from context
    loop tokens
        A-->>B: SSE token
    end
    A-->>B: SSE done
```

### 5.2 Booking with human-in-the-loop

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as FastAPI
    participant G as LangGraph
    participant M as MCP server
    participant P as Postgres

    B->>A: POST /chat "Book a men's haircut tomorrow 4pm, I'm Yash, 98765 43210"
    A->>G: astream
    G->>M: tools/call list_services, check_availability
    M->>P: query services, hours, bookings
    A-->>B: SSE tool_call / tool_result
    G->>G: booking_agent wants book_appointment
    G->>G: confirm: validate ids + grounding guardrail
    G->>P: checkpoint state, interrupt()
    A-->>B: SSE confirm {Book appointment, Service, Date, Time, Name, Phone}
    Note over B: Customer clicks Confirm
    B->>A: POST /chat/resume {approved: true}
    A->>G: astream(Command(resume))
    G->>M: tools/call book_appointment
    M->>P: INSERT booking (exclusion constraint guards overlaps)
    A-->>B: SSE tool_result, token "You're booked for Sunday at 4pm"
    A-->>B: SSE done
```

### 5.3 Document ingestion

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as FastAPI
    participant BG as Background task
    participant L as Gemini embeddings
    participant P as Postgres

    B->>A: POST /businesses/{id}/documents (file)
    A->>P: insert document (processing)
    A-->>B: 202 Accepted
    A->>BG: ingest_document()
    BG->>BG: extract text · chunk
    BG->>L: embed (batches of 100)
    BG->>P: insert chunks, status=ready
    loop every 2s while processing
        B->>A: GET documents
    end
```

---

## 6. Data model

```mermaid
erDiagram
    BUSINESSES ||--o{ DOCUMENTS : has
    BUSINESSES ||--o{ CHUNKS : "owns (tenant filter)"
    DOCUMENTS ||--o{ CHUNKS : "split into"
    BUSINESSES ||--o{ SERVICES : offers
    BUSINESSES ||--o{ BUSINESS_HOURS : "open on"
    BUSINESSES ||--o{ BOOKINGS : receives
    SERVICES ||--o{ BOOKINGS : "booked as"

    BUSINESSES {
        uuid id PK
        string name
        text description
        string timezone "IANA, e.g. Asia/Kolkata"
        string currency
    }
    DOCUMENTS {
        uuid id PK
        uuid business_id FK
        string filename
        enum status "processing | ready | failed"
        int num_chunks
    }
    CHUNKS {
        uuid id PK
        uuid business_id FK
        uuid document_id FK
        text content
        vector embedding "768-d, HNSW cosine"
        tsvector tsv "generated, GIN"
    }
    SERVICES {
        uuid id PK
        uuid business_id FK
        string name
        int duration_minutes
        int price
        bool active "deactivate, never delete"
    }
    BUSINESS_HOURS {
        int id PK
        uuid business_id FK
        smallint weekday "0=Mon..6=Sun, unique per business"
        time opens_at
        time closes_at
    }
    BOOKINGS {
        uuid id PK
        uuid business_id FK
        uuid service_id FK
        string customer_name
        string customer_phone "normalised"
        timestamptz start_at
        timestamptz end_at
        enum status "confirmed | cancelled"
    }
```

Key constraint: `bookings` has `EXCLUDE USING gist (business_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&) WHERE (status = 'confirmed')`
— the database rejects overlapping confirmed bookings, even under concurrent requests.

LangGraph's checkpoint tables live in the same database and are managed by LangGraph, not Alembic.

---

## 7. Key design decisions

Full list with dates in [`PROGRESS.md`](PROGRESS.md#decision-log); explanations in
[`interview/`](interview/00_INDEX.md).

| Decision | Why |
|---|---|
| Explicit LangGraph state machine | Predictable, testable control flow; checkpointing, streaming, interrupts built in |
| pgvector in the main Postgres | One database for app data, vectors and agent memory; SQL tenant filtering |
| Hybrid search fused with RRF | Semantic + keyword fail differently; RRF merges ranks without score normalisation |
| Booking tools as a separate MCP server | Decoupled, independently deployable/securable, usable by any MCP client |
| Tenant via MCP connection header, not tool args | The LLM can't choose (or be tricked into) another business |
| Human-in-the-loop only for write tools | Safety for real-world actions without confirmation fatigue |
| Guardrail validates write args before asking the human | LLMs ignore prompt rules sometimes; invariants are enforced in code |
| Exclusion constraint for bookings | Only the database can prevent double booking under concurrency |
| Booking agent sees last 3 full turns | Reuses real ids from earlier tool results instead of guessing |
| SSE for chat, WebSocket for voice (planned) | One-way token stream vs two-way audio stream |

---

## 8. Drawing this in draw.io (or Excalidraw / Lucidchart)

**Fastest: import the Mermaid code**
1. Open [app.diagrams.net](https://app.diagrams.net) → blank diagram.
2. **Arrange → Insert → Advanced → Mermaid…**
3. Paste a diagram's code (everything between ` ```mermaid ` and ` ``` `) → **Insert**.
4. The result is editable shapes — drag to tidy the layout, recolour, add icons.
5. Save as `docs/diagrams/voxdesk-architecture.drawio` and export a PNG for the README.

**Drawing by hand (e.g. live in an interview)** — use the System overview (section 1), left to right:

1. **Clients** — customer (chat/voice), business owner.
2. **Frontend** — Next.js.
3. **API layer** — FastAPI (REST + SSE; later WebSocket for voice).
4. **Orchestration** — LangGraph supervisor (sketch route → retrieve/respond and booking_agent ⇄ tools with a ⏸ confirm).
5. **Tools & agents** — MCP server (booking tools); later A2A knowledge + booking agents.
6. **Data** — Postgres + pgvector (one cylinder, list what it stores), Redis.
7. **External** — Gemini API (cloud shape).

Conventions: data stores as cylinders, external services as clouds, label every arrow with its
protocol (**HTTP/SSE, WebSocket, MCP, A2A, SQL**), dashed lines for async or planned paths, one
colour per layer.
