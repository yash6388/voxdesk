# VoxDesk — Interview Notes (Index)

These notes explain **what was built, how it works, and why each decision was made**, in plain
language, so you can explain any part of VoxDesk confidently in an interview.

Each file is written right after the phase it covers, while the details are fresh.

## How to use these notes

1. Read a topic file top to bottom once — it goes from "plain English" → "how it works" → "why".
2. Open the code files it references and match each explanation to real lines.
3. Practise the **"Say it like this"** boxes out loud — those are interview-ready answers.
4. Go through the **Q&A** at the end of each file; cover the answer and try first.

> **Diagrams:** see [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — system overview, sequence flows and data model (Mermaid; importable into draw.io).

## Topic files (written as we build)

| # | File | Covers | Status |
|---|---|---|---|
| 01 | [01_foundations.md](01_foundations.md) | Monorepo, uv, Docker Compose, config, Alembic migrations, CI | ✅ Phase 0–1 |
| 02 | [02_rag_pipeline.md](02_rag_pipeline.md) | Ingestion, chunking, embeddings, pgvector, hybrid search, RRF, indexes, multi-tenancy | ✅ Phase 1 |
| 03 | [03_langgraph_agent.md](03_langgraph_agent.md) | LangGraph state machine, router, query rewriting, memory/checkpointer, SSE streaming | ✅ Phase 1 |
| 04 | [04_testing.md](04_testing.md) | Testing strategy: fakes for LLMs/embeddings, real Postgres, CI | ✅ Phase 1 |
| 05 | [05_frontend.md](05_frontend.md) | Next.js app, typed API client, reading SSE streams, history restore, upload polling, CORS | ✅ Phase 1 |
| 06 | [06_mcp.md](06_mcp.md) | MCP server + client, tool design, tenant security, exclusion constraint, booking agent, human-in-the-loop, guardrails, live-test bugs | ✅ Phase 2 |
| 07 | [07_a2a.md](07_a2a.md) | A2A protocol, Agent Cards, tasks/artifacts, MCP vs A2A, why split services, supervisor delegation, HITL over A2A, testing the protocol | ✅ Phase 3 |
| 08 | [08_voice.md](08_voice.md) | Voice pipeline, local vs ElevenLabs, WebSocket, sentence-streaming TTS, spoken confirmation, barge-in, latency | ✅ Phase 4 |
| 09 | `09_production.md` | Tracing, evals, auth, rate limiting, deployment | ⏳ Phase 5 |

## Final files (written at the end, once everything is built)

| File | Purpose |
|---|---|
| `PROJECT_EXPLAINED.md` | The whole project end to end in one place: architecture, every component, data flow, numbers, trade-offs, limitations |
| `PITCH.md` | Exactly how to present VoxDesk to an interviewer: 30-second, 2-minute and 5-minute versions, whiteboard diagram, and how to steer follow-ups |
| `SYSTEM_DESIGN.md` | Answering "design this system" rounds: requirements → capacity estimates → high-level design → deep dives (RAG, agents, voice latency) → data model → scaling to 10k businesses → failure handling → trade-offs; with a step-by-step whiteboard script |

## Glossary (quick lookup)

| Term | One-line meaning |
|---|---|
| **LLM** | Large Language Model — here, Google Gemini |
| **RAG** | Retrieval-Augmented Generation: find relevant text first, then let the LLM answer *from that text* |
| **Embedding** | A list of numbers (a vector) representing the meaning of a text; similar meanings → nearby vectors |
| **Vector DB / pgvector** | Storage that can find "nearest" vectors fast; pgvector adds this to PostgreSQL |
| **Chunk** | A small piece of a document (~1000 characters) that gets embedded and retrieved |
| **Hybrid search** | Combining semantic (vector) search with keyword (full-text) search |
| **RRF** | Reciprocal Rank Fusion — a simple formula to merge two ranked lists |
| **HNSW** | The graph-based index pgvector uses for fast approximate nearest-neighbour search |
| **LangGraph** | A library to build LLM apps as explicit graphs of steps (nodes) with shared state |
| **Checkpointer** | LangGraph component that saves graph state after each step — gives the agent memory |
| **SSE** | Server-Sent Events — the server pushes a stream of messages to the browser over one HTTP response |
| **Multi-tenant** | One system serving many customers (businesses) with their data kept separate |
| **MCP** | Model Context Protocol — standard for AI apps to discover and call tools in a separate server |
| **Tool call** | The LLM asking the app to run a named function with JSON arguments |
| **Human-in-the-loop (HITL)** | The agent pauses and a person approves before an action runs |
| **interrupt()** | LangGraph function that checkpoints the graph and pauses it until resumed |
| **Exclusion constraint** | Postgres rule that no two rows may "conflict" (here: overlapping time ranges) |
| **Guardrail** | A code check that stops or corrects unsafe/invalid LLM output |
| **A2A** | Agent2Agent protocol — agents discover each other (Agent Cards) and delegate tasks over HTTP |
| **Agent Card** | Public JSON describing an agent's skills, endpoint, capabilities and auth |
| **Task (A2A)** | A unit of delegated work with a lifecycle (working, completed, input-required, failed…) |
| **Artifact (A2A)** | An output of a task, e.g. a streamed answer or a list of sources |
| **Supervisor** | The orchestrating agent that routes and delegates to specialist agents |
| **STT / ASR** | Speech-to-text (automatic speech recognition) — here faster-whisper |
| **TTS** | Text-to-speech — here Kokoro (local) or ElevenLabs |
| **WebSocket** | A persistent two-way connection; used for streaming audio both ways |
| **Barge-in** | The caller interrupts the agent mid-sentence and the agent stops |
| **VAD** | Voice activity detection — detecting when someone starts/stops speaking |
| **Time to first audio** | Delay until the caller hears the first word — the key voice latency metric |
| **Quantisation (int8)** | Storing model weights in 8-bit integers: smaller, faster, tiny accuracy loss |
| **Migration** | A versioned script that changes the database schema (Alembic) |
| **CI** | Continuous Integration — automatic lint + tests on every push (GitHub Actions) |
