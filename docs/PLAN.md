# VoxDesk — Project Plan

## 1. What we're building

**VoxDesk** is a multi-agent voice AI agent platform for small businesses.

- A **business** (clinic, salon, restaurant) signs up, uploads its documents (prices, policies, FAQs) and configures its services and available slots.
- A **customer** talks to the business's agent — by voice in the browser, or by text chat.
- The agent **answers questions** from the business's own documents (RAG), **books / reschedules / cancels appointments** (MCP tools), and **escalates to a human** when it can't help.
- A **dashboard** shows live transcripts, which agent handled each step, bookings, and call analytics.

**Resume line (target):** *Multi-agent voice AI platform that handles customer conversations for businesses — answers questions via RAG, books appointments via a custom MCP server, and delegates between specialist agents using the A2A protocol.*

## 2. Why this project (interview goals)

FilingLens (existing project) already proves RAG + evaluation. VoxDesk adds what interviewers ask about and FilingLens doesn't show:

| Skill | Where it shows up in VoxDesk |
|---|---|
| Agentic workflows (LangGraph) | Supervisor graph, routing, human-in-the-loop interrupt, checkpointed memory, streaming |
| MCP | **Built** our own MCP server (FastMCP) **and** consumed MCP tools from LangGraph |
| A2A | Specialist agents run as independent A2A services with Agent Cards; supervisor delegates via A2A client |
| RAG | Per-business knowledge base on pgvector, hybrid search (vector + Postgres full-text, RRF) |
| Voice AI | Custom STT → agent → TTS streaming pipeline with latency measurements |
| Production thinking | Tracing (Langfuse), evals, auth, rate limiting, Docker, CI, deployment |

## 3. Architecture

> Detailed, always-current diagrams (components, sequence flows, data model): [`ARCHITECTURE.md`](ARCHITECTURE.md)

```
                         Next.js frontend
          (text chat · voice UI · business admin dashboard)
                 │ SSE (text)        │ WebSocket (audio)
                 ▼                   ▼
        ┌──────────────── FastAPI Gateway (backend/) ─────────────────┐
        │  REST API · auth · STT (speech→text) · TTS (text→speech)    │
        │                                                             │
        │      LangGraph Supervisor  (Gemini 2.5 Flash)               │
        │      - classifies intent, routes, keeps conversation state  │
        │      - Postgres checkpointer (memory across turns)          │
        │      - human-in-the-loop interrupt before confirming booking│
        └───────┬───────────────────────────┬─────────────────────────┘
                │ A2A                        │ A2A
                ▼                            ▼
     Knowledge Agent (agents/)       Booking Agent (agents/)
     RAG over business docs          manages appointments
     pgvector + full-text, RRF               │ MCP (client)
                                             ▼
                                  VoxDesk MCP Server (mcp_servers/)
                                  tools: list_services, check_availability,
                                  book_appointment, reschedule, cancel
                                             │
        ┌────────────────────────────────────┴───────────────────────┐
        │ PostgreSQL 16 + pgvector  ·  Redis  ·  Langfuse (tracing)  │
        └────────────────────────────────────────────────────────────┘
```

**Key concepts in one line each**
- **MCP** connects an agent to **tools** (our server exposes booking operations; any MCP client — our agent, Claude Desktop, Cursor — can use them).
- **A2A** connects an agent to **other agents** (supervisor discovers specialists via Agent Cards and delegates tasks over HTTP).
- **RAG** grounds answers in each business's own documents instead of LLM guesses.
- **Voice pipeline** is transport-agnostic: audio in → STT → graph → TTS → audio out. Browser now; phone (Twilio) could be another adapter later.

## 4. Tech decisions (and why)

| Area | Choice | Why |
|---|---|---|
| Frontend | Next.js (App Router, TS, Tailwind) | Industry standard; SSR dashboard + client-side voice UI |
| Backend | FastAPI (Python 3.13, uv) | Async-first, fits I/O-heavy LLM/audio work; uv = fast modern packaging |
| Orchestration | LangGraph + LangChain | Explicit, inspectable state machine; interrupts, checkpointing, streaming built in |
| LLM | Gemini 2.5 Flash (Google GenAI API) | Generous free tier, fast, good tool calling |
| Embeddings | Gemini embeddings (`gemini-embedding-001`) | No local GPU needed; same provider as LLM |
| Vector store | pgvector (inside Postgres) | Postgres already stores bookings + checkpoints → one DB; tenant filtering is just SQL; adds breadth beyond FilingLens's Qdrant |
| Keyword search | Postgres full-text (`tsvector`) | Hybrid search in the same DB, fused with RRF |
| MCP | `mcp` Python SDK (FastMCP) + `langchain-mcp-adapters` | Official SDK; adapters turn MCP tools into LangChain tools |
| A2A | `a2a-sdk` (official Python SDK) | Official protocol implementation; Agent Cards, task lifecycle |
| STT | faster-whisper (local, open-source) — fallback Deepgram | Free, private; swap via interface |
| TTS | Kokoro (open-source) or ElevenLabs free tier | Compare quality vs latency; swap via interface |
| DB access | SQLAlchemy 2.0 async + Alembic | Typed models, migrations |
| Cache / rate limit | Redis | Response cache, rate limiting, pub/sub for live dashboard |
| Observability | Langfuse | Open-source LLM tracing, cost + latency per step |
| Infra | Docker Compose, GitHub Actions CI | One-command start; lint + tests on every push |

## 5. Phases

Each phase ends with something demoable and a commit.

### Phase 0 — Setup ✅
- Repo, `CLAUDE.md`, docs, `.gitignore`, `.env.example`, README skeleton
- `backend/`: FastAPI app with uv, `/health`, config via pydantic-settings, ruff, pytest
- `frontend/`: Next.js app (TS, Tailwind) talking to `/health`
- `docker-compose.yml`: Postgres+pgvector, Redis
- GitHub Actions CI: ruff + pytest + frontend lint/build

### Phase 1 — Text core + RAG ✅
- DB models: business, document, chunk (with vector + tsvector), conversation; Alembic migrations
- Upload docs → parse → chunk → embed → store
- Hybrid retrieval (pgvector + full-text, RRF)
- LangGraph supervisor v1 with a RAG node; Postgres checkpointer
- `/chat` endpoint with SSE streaming; Next.js chat page + doc upload page
- *(Built: see `docs/PROGRESS.md` for details and `docs/interview/02–05` for explanations)*

### Phase 2 — MCP ✅
- MCP server (built in `backend/app/mcp/`, runs as its own process on :8001): FastMCP over streamable HTTP; tools for services, availability, book, reschedule, cancel; validation (no double booking, no past slots)
- LangGraph loads tools via `langchain-mcp-adapters`
- Human-in-the-loop: graph `interrupt()` → user confirms booking → resume
- Bonus: connect Claude Desktop to our MCP server (demo of decoupling)
- *(Built: see `docs/PROGRESS.md` and `docs/interview/06_mcp.md`)*

### Phase 3 — A2A ✅
- Move RAG into a Knowledge agent and booking logic into a Booking agent, each an A2A server with an Agent Card (built in `backend/app/agents/`, separate processes)
- Supervisor becomes an A2A client: discovers agents, delegates tasks, streams results
- Escalation path → human handoff (flag conversation in dashboard) — moved to Phase 5
- *(Built: see `docs/PROGRESS.md` and `docs/interview/07_a2a.md`)*

### Phase 4 — Voice
- WebSocket audio endpoint; browser mic capture in Next.js
- STT interface (faster-whisper) → graph → TTS interface (Kokoro / ElevenLabs), streamed back
- Push-to-talk first; then VAD + barge-in (user interrupts the agent)
- Measure latency per stage (STT, LLM first token, TTS first audio)

### Phase 5 — Production polish
- Langfuse tracing; eval suite (retrieval hit rate, tool-call accuracy, end-to-end latency)
- Auth (JWT) for business dashboard, rate limiting, input guardrails, cost tracking
- Dashboard: transcripts, agent trace per turn, bookings, analytics
- Deploy (Vercel for frontend; Render/Fly for backend + services)
- README with architecture diagram + demo GIF

### Later upgrades (optional)
Twilio phone calls · GraphRAG (Neo4j) · Hindi/multilingual voice · outbound reminder-call agent · Google Calendar sync via external MCP server

## 6. Documentation plan

- `docs/PLAN.md` (this file) — plan & decisions
- `docs/PROGRESS.md` — running progress + decision log (updated every session)
- `docs/ARCHITECTURE.md` — living architecture with Mermaid diagrams (renders on GitHub, importable into draw.io); updated every phase
- `docs/interview/` — beginner-friendly interview notes, **one topic file per phase, written right after that phase** (index in `00_INDEX.md`).
- **At the very end:** `docs/interview/PROJECT_EXPLAINED.md` (whole project end to end) `docs/interview/PITCH.md` (how to present it: 30s / 2min / 5min versions), and `docs/interview/SYSTEM_DESIGN.md` (HLD for system-design rounds: requirements, estimates, components, scaling, failures, trade-offs).
