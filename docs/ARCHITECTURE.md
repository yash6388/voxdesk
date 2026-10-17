# VoxDesk — Architecture

> How VoxDesk is built: system overview, deployment, components, agent graphs, request flows, data
> model and key design decisions. Diagrams are [Mermaid](https://mermaid.js.org/) — GitHub renders
> them automatically, and draw.io can import them (see the last section).

---

## 1. System overview

```mermaid
flowchart LR
    customer(["Customer<br/>browser chat / voice"])
    owner(["Business owner<br/>dashboard"])

    subgraph FE["Frontend · Next.js"]
        ui["Landing · Dashboard · Playground<br/>Knowledge · Bookings · Inbox<br/>Analytics · Share · Widget"]
    end

    subgraph BE["API · FastAPI"]
        api["REST + SSE API"]
        voice["Voice WebSocket<br/>STT · TTS per sentence"]
        sup["Supervisor graph<br/>route · small talk · handoff<br/>memory · confirm ⏸"]
    end

    subgraph AG["Specialist agents · A2A services"]
        ka["Knowledge agent :8101<br/>hybrid RAG"]
        ba["Booking agent :8102<br/>booking graph · own memory"]
    end

    mcp["VoxDesk MCP server :8001<br/>7 booking tools"]

    subgraph DATA["Data"]
        pg[("PostgreSQL 16 + pgvector<br/>businesses · documents · chunks<br/>services · hours · bookings<br/>conversations · turns · checkpoints")]
        redis[("Redis<br/>rate limits")]
    end

    gemini["Google Gemini API<br/>chat · embeddings"]

    customer --> ui
    owner --> ui
    ui -- "HTTP / SSE" --> api
    ui -- "WebSocket audio" --> voice
    voice --> sup
    api --> sup
    sup -- "A2A · JSON-RPC + SSE" --> ka
    sup -- "A2A · JSON-RPC + SSE" --> ba
    ba -- "MCP · Streamable HTTP" --> mcp
    sup --> pg
    ka --> pg
    ba --> pg
    mcp --> pg
    sup --> gemini
    ka --> gemini
    ba --> gemini
    api --> redis
```

| Component | Responsibility | Tech |
|---|---|---|
| Frontend | Landing page; dashboard: businesses, knowledge base, services & hours, bookings, Inbox, analytics, share page; playground with agent inspector; public customer page + embeddable widget | Next.js, TypeScript, Tailwind, Lucide |
| API | Owner REST (auth, businesses, documents, services, hours, bookings, analytics, inbox), SSE chat + resume, guardrails, rate limits | FastAPI, Pydantic |
| Supervisor graph | Routing + query rewrite, small talk, conversation memory, delegation over A2A, confirmation pause | LangGraph, Gemini, a2a-sdk client |
| Knowledge agent | A2A service: hybrid retrieval + grounded, streamed answer with sources | a2a-sdk, pgvector, Gemini |
| Booking agent | A2A service: booking graph (LLM + MCP tools + guardrails), own memory, `input-required` for confirmation | a2a-sdk, LangGraph, langchain-mcp-adapters |
| MCP server | Booking tools usable by any MCP client; auth + tenant headers | FastMCP (`mcp` SDK), Streamable HTTP |
| Booking domain | Availability, validation, booking rules shared by MCP + REST | SQLAlchemy, Postgres exclusion constraint |
| Voice | `/voice` WebSocket: speech → STT → supervisor → per-sentence TTS → audio; spoken confirmation; barge-in; latency metrics | faster-whisper + Kokoro (local, default) or ElevenLabs |
| PostgreSQL | System of record + vectors + checkpoints (supervisor and booking agent) | Postgres 16 + pgvector + btree_gist |
| Redis | Rate limiting (fixed-window counters) | Redis 7 |
| Tracing | One trace per turn across API + A2A agents (LLM calls, tools, retrieval, STT/TTS) | Langfuse (OpenTelemetry) |

---

## 2. Deployment (local / Docker Compose)

```mermaid
flowchart TB
    browser(["Browser"])
    other(["Any A2A / MCP client"])
    subgraph host["Developer machine"]
        next["Next.js dev server :3000"]
        fastapi["API + supervisor · uvicorn :8000"]
        knowledge["Knowledge agent · :8101"]
        bookingagent["Booking agent · :8102"]
        mcpserver["MCP server · :8001"]
        subgraph docker["Docker Compose"]
            pg[("pgvector/pgvector:pg16<br/>host :5433")]
            redis[("redis:7-alpine<br/>host :6380")]
        end
    end
    gemini["Gemini API"]

    browser --> next
    browser -- "fetch / SSE · CORS" --> fastapi
    fastapi -- "A2A · Bearer A2A key" --> knowledge
    fastapi -- "A2A · Bearer A2A key" --> bookingagent
    bookingagent -- "MCP · Bearer MCP key + X-Business-Id" --> mcpserver
    other -. "Agent Card / MCP" .-> knowledge
    other -.-> mcpserver
    fastapi --> pg
    knowledge --> pg
    bookingagent --> pg
    mcpserver --> pg
    fastapi --> gemini
    knowledge --> gemini
    bookingagent --> gemini
```

Run locally: `docker compose up -d`, `./scripts/dev_services.sh` (MCP + both agents), the API
(`uvicorn app.main:app --reload`) and the frontend (`npm run dev`) — **or everything in containers:
`docker compose --profile app up -d --build`** (one backend image runs as `api`, `mcp`, `knowledge`,
`booking`; plus `frontend`, `postgres`, `redis`; healthchecks gate start-up order; services reach each
other by name, e.g. `http://knowledge:8101`).

---

## 3. Backend components

```mermaid
flowchart TB
    subgraph apiproc["API process"]
        chat["api/chat.py · api/voice.py<br/>SSE · WebSocket"]
        rec["analytics.py<br/>TurnRecorder"]
        rest["api/businesses · documents · booking"]
        ins["api/insights.py<br/>analytics · inbox"]
        sup["graph/supervisor.py"]
        client["a2a/client.py<br/>A2AAgent"]
    end
    subgraph kproc["Knowledge agent process"]
        kexec["agents/knowledge.py<br/>executor + Agent Card"]
        ret["rag/retrieval.py<br/>hybrid + RRF"]
    end
    subgraph bproc["Booking agent process"]
        bexec["agents/booking.py<br/>executor + Agent Card"]
        bgraph["graph/booking_graph.py<br/>agent · tools · confirm"]
        tools["graph/tools.py<br/>MCPToolProvider"]
    end
    subgraph mproc["MCP server process"]
        mcp["mcp/server.py<br/>7 tools"]
    end
    svc["booking/service.py<br/>rules (shared)"]
    shared["a2a/server.py · llm.py · security.py<br/>graph/checkpoint.py · db/"]

    chat --> sup --> client
    chat -- "events" --> rec
    client -- A2A --> kexec
    client -- A2A --> bexec
    kexec --> ret
    bexec --> bgraph --> tools
    tools -- MCP --> mcp
    mcp --> svc
    rest --> svc
    kexec -.-> shared
    bexec -.-> shared
```

All four processes share one Python package (`backend/app`) — one codebase, separately deployable
services. Booking rules live once in `app/booking/service.py`.

---

## 4. Agent graphs (LangGraph)

### 4.1 Supervisor (API)

```mermaid
flowchart LR
    S((START)) --> route["route<br/>flash-lite · structured output<br/>intent + standalone query"]
    route -- knowledge --> k["knowledge<br/>delegate → Knowledge agent (A2A)"]
    route -- smalltalk --> respond["respond<br/>local LLM"]
    route -- booking --> b["booking<br/>delegate → Booking agent (A2A)"]
    route -- handoff --> h["handoff<br/>reply + flag for staff (Inbox)"]
    k --> E((END))
    h --> E
    respond --> E
    b -- completed --> E
    b -- "input-required" --> c{{"booking_confirm<br/>⏸ interrupt → reply on same A2A task"}}
    c -- completed --> E
    c -- "input-required again" --> c
```

### 4.2 Booking agent (inside the Booking agent service)

```mermaid
flowchart LR
    S((START)) --> agent["booking_agent<br/>LLM + MCP tools"]
    agent -- "no tool calls" --> E((END))
    agent -- "read tools" --> tools["tools<br/>call MCP"]
    agent -- "write tools" --> confirm{{"confirm<br/>validate + guardrail<br/>⏸ interrupt → A2A input-required"}}
    confirm -- approved --> tools
    confirm -- "declined / invalid" --> agent
    tools --> agent
```

Supervisor state is checkpointed under `{business_id}:{thread_id}`; the booking agent's under
`booking:{context_id}` (same Postgres, separate threads).

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

### 5.2 Booking with human-in-the-loop (across agents)

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant S as API · Supervisor
    participant A as Booking agent (A2A)
    participant M as MCP server
    participant P as Postgres

    B->>S: POST /chat "Book a men's haircut Tue 11am, I'm Yash, 98765 43210"
    S->>A: A2A SendMessage (text + business metadata, context = thread)
    A->>M: tools/call list_services, check_availability
    A-->>S: artifacts tool_call / tool_result
    S-->>B: SSE delegation, tool_call, tool_result
    A->>A: confirm: validate ids + grounding guardrail, interrupt()
    A-->>S: status INPUT_REQUIRED {actions}
    S->>S: store pending task, interrupt() (checkpoint)
    S-->>B: SSE confirm (card)
    Note over B: Customer clicks Confirm
    B->>S: POST /chat/resume {approved: true}
    S->>A: A2A SendMessage on SAME task {approved: true}
    A->>M: tools/call book_appointment
    M->>P: INSERT booking (exclusion constraint guards overlaps)
    A-->>S: streamed answer artifact, COMPLETED
    S-->>B: SSE tokens "You're booked…", done
```

### 5.3 Voice turn (sentence-by-sentence speech)

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant V as API /voice (WebSocket)
    participant STT as STT (faster-whisper)
    participant S as Supervisor + A2A agents
    participant TTS as TTS (Kokoro)

    B->>V: binary: recorded utterance (webm/opus)
    V->>STT: decode to 16 kHz mono, transcribe
    STT-->>V: "Do you have parking?"
    V-->>B: transcript
    V->>S: run turn (same graph as chat)
    loop tokens stream in
        S-->>V: token
        V-->>B: token (live transcript)
        Note over V: sentence complete → queue for speaker task
    end
    loop each complete sentence, while the agent keeps generating
        V->>TTS: synthesize sentence 1
        TTS-->>V: WAV
        V-->>B: audio meta + binary frame (plays immediately)
    end
    V-->>B: timing {stt, first token, first audio, total}, turn_end
```

### 5.4 Document ingestion

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
    USERS ||--o{ BUSINESSES : owns
    BUSINESSES ||--o{ DOCUMENTS : has
    BUSINESSES ||--o{ CHUNKS : "owns (tenant filter)"
    DOCUMENTS ||--o{ CHUNKS : "split into"
    BUSINESSES ||--o{ SERVICES : offers
    BUSINESSES ||--o{ BUSINESS_HOURS : "open on"
    BUSINESSES ||--o{ BOOKINGS : receives
    SERVICES ||--o{ BOOKINGS : "booked as"
    BUSINESSES ||--o{ CONVERSATIONS : has
    CONVERSATIONS ||--o{ TURNS : "made of"

    USERS {
        uuid id PK
        string email "unique, lowercase"
        string name
        string password_hash "argon2id"
    }
    BUSINESSES {
        uuid id PK
        uuid owner_id FK
        string slug "unique, public URL /c/slug"
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
    CONVERSATIONS {
        uuid id PK
        uuid business_id FK
        string thread_id "unique per business = LangGraph thread"
        string channel "chat | voice"
        enum status "open | needs_human | resolved"
        string handoff_reason
        int turn_count
        timestamptz last_activity_at
    }
    TURNS {
        uuid id PK
        uuid conversation_id FK
        uuid business_id FK "indexed with created_at"
        string intent "knowledge | booking | smalltalk | handoff"
        string outcome "answered | booked | handoff | guardrail | error ..."
        text user_text "preview"
        text reply_text "preview"
        int first_token_ms
        int total_ms
    }
```

Key constraint: `bookings` has `EXCLUDE USING gist (business_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&) WHERE (status = 'confirmed')`
— the database rejects overlapping confirmed bookings, even under concurrent requests.

`conversations`/`turns` are written by `TurnRecorder` with one upsert per turn
(`INSERT … ON CONFLICT (business_id, thread_id) DO UPDATE`); full transcripts are **not** copied —
the Inbox reads them from the LangGraph checkpoint.

LangGraph's checkpoint tables live in the same database and are managed by LangGraph, not Alembic.

---

## 7. Key design decisions

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
| Specialists as A2A services, supervisor keeps the conversation | Independent scaling/deployment, failure isolation, least privilege, interoperability |
| Supervisor sends the rewritten standalone query to the knowledge agent | Knowledge agent stays stateless and simple |
| Booking confirmation = A2A `input-required` + supervisor `interrupt()` | HITL maps onto the protocol's task lifecycle; UI/API contract unchanged |
| Business info as metadata on every A2A message | A2A doesn't persist request metadata across messages |
| Agent Card public, JSON-RPC bearer-protected | Discovery is the point of a card; calling needs credentials |
| Owner auth: JWT in httpOnly cookie; owner-only routers return 404 for other tenants | XSS-safe sessions, tenant isolation, no id enumeration |
| Public customer page by slug; chat/voice endpoints public | Customers never need an account |
| Langfuse tracing with trace ids passed over A2A | Debug a multi-agent, multi-process turn as one timeline |
| SSE for chat, WebSocket for voice | One-way token stream vs two-way audio + control stream |
| Local STT/TTS by default, ElevenLabs by config | Free/private/no quotas for dev; best quality when needed; same interface |
| Per-sentence TTS pipelined with LLM streaming | Caller hears the first sentence long before the answer is finished |
| Chunk size 500/100 chosen by the evaluation suite | Hit@1 86% vs 82% at 1000 (equal overlap) |
| LLM fallback: Gemini → any OpenAI-compatible provider (chat only, not embeddings) | Survive provider outages/quotas; embeddings must stay one model to remain comparable |
| Analytics derived from the client event stream (`TurnRecorder`) | Same code for chat and voice; graph and agents know nothing about analytics |
| Handoff = route → flag `needs_human` → Inbox; no repeat handoff (rule in code) | Real follow-up workflow without a live takeover console; router LLM was unreliable on follow-ups |
| Decode audio with PyAV directly | faster-whisper's helper is incompatible with current PyAV; also format-agnostic |

---

## 8. Drawing this in draw.io (or Excalidraw / Lucidchart)

**Fastest: import the Mermaid code**
1. Open [app.diagrams.net](https://app.diagrams.net) → blank diagram.
2. **Arrange → Insert → Advanced → Mermaid…**
3. Paste a diagram's code (everything between ` ```mermaid ` and ` ``` `) → **Insert**.
4. The result is editable shapes — drag to tidy the layout, recolour, add icons.
5. Save as `docs/diagrams/voxdesk-architecture.drawio` and export a PNG for the README.

**Drawing by hand (e.g. on a whiteboard)** — use the System overview (section 1), left to right:

1. **Clients** — customer (chat/voice), business owner.
2. **Frontend** — Next.js.
3. **API layer** — FastAPI (REST + SSE; later WebSocket for voice).
4. **Orchestration** — LangGraph supervisor (route → delegate, ⏸ confirm).
5. **Agents & tools** — Knowledge agent and Booking agent (A2A); the booking agent calls the MCP server (tools).
6. **Data** — Postgres + pgvector (one cylinder, list what it stores), Redis.
7. **External** — Gemini API (cloud shape).

Conventions: data stores as cylinders, external services as clouds, label every arrow with its
protocol (**HTTP/SSE, WebSocket, MCP, A2A, SQL**), dashed lines for async or planned paths, one
colour per layer.
