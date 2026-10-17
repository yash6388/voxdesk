# VoxDesk — Progress Log

> Update at the end of every work session: tick tasks, set "Next up", add decisions.

## Current status
**Phase 3 — A2A ✅ done** · next: **agreed review checkpoint before Phase 4 (voice)**

### Phase 3 done
- [x] `a2a-sdk` 1.2 (v1, protobuf types); prototyped streaming + input-required + resume first (found the "first artifact chunk must not append" rule)
- [x] `app/a2a/server.py` (Agent Card builder, app factory with bearer auth, `TextStream`, `emit_data`) and `app/a2a/client.py` (`A2AAgent`: card discovery, streaming → simple events)
- [x] **Knowledge agent** (`app/agents/knowledge.py`, :8101): hybrid RAG, streamed answer artifact + sources artifact
- [x] **Booking agent** (`app/agents/booking.py`, :8102): booking graph moved in (`graph/booking_graph.py`), own Postgres memory, graph interrupt → A2A `input-required`, resume on same task
- [x] **Supervisor** (`graph/supervisor.py`): route → delegate (knowledge/booking) or local small talk; relays agent stream via LangGraph custom stream; `booking_confirm` interrupt ↔ A2A input-required; fallbacks when agents fail
- [x] Shared modules: `llm.py`, `security.py` (BearerKeyMiddleware, also used by MCP), `errors.py`, `graph/common.py`, `graph/checkpoint.py`; `builder.py` removed
- [x] Chat API: `custom` stream mode, new `delegation` SSE event; UI/API contract otherwise unchanged
- [x] Frontend: Agent Inspector shows the handling A2A agent, task id and state
- [x] `scripts/dev_services.sh` runs MCP + both agents with labelled logs
- [x] `GET /health/services` readiness check (DB, MCP, both agents in parallel, 2 s timeout each; MCP got a public `/health`); sidebar shows overall status + per-service hover panel
- [x] 47 tests: real A2A protocol in-process (card, 401, streaming, input-required → resume), supervisor delegation/HITL/fallbacks, booking graph
- [x] Live: Agent Cards served publicly, JSON-RPC without key → 401; full Gemini conversation blocked by free-tier 429 (graceful message shown end to end)

### Phase 2 done
- [x] Models + migration: `services`, `business_hours`, `bookings` (+ `businesses.timezone/currency`); **exclusion constraint** (btree_gist) prevents overlapping confirmed bookings
- [x] `app/booking/service.py`: availability (30-min steps, hours, past, 60-day horizon), create/find/cancel/reschedule, phone normalisation; shared by MCP + REST
- [x] **MCP server** `app/mcp/server.py` (FastMCP, Streamable HTTP :8001, stateless): 7 tools; bearer-key middleware; tenant from `X-Business-Id` header (no `business_id` in tool schemas)
- [x] **Booking agent** in LangGraph: `booking_agent ⇄ tools` via `langchain-mcp-adapters`; write tools → `confirm` node with `interrupt()` → `/chat/resume`
- [x] Guardrails: ids validated + **customer name/phone grounded in customer messages** before confirmation; booking agent sees last 3 full turns; graceful reply if MCP is down
- [x] Rate-limit handling: LLM `max_retries=2`, friendly 429 message
- [x] Owner REST: services (create, activate/deactivate), hours (replace week), bookings (list, owner cancel)
- [x] Frontend: Services & hours page, Bookings page (auto-refresh, business timezone), confirmation card in chat (survives reload), Inspector shows MCP tool calls; sidebar updated; landing copy updated (no jargon)
- [x] `scripts/seed_demo.py` (idempotent demo data)
- [x] 39 backend tests (23 new): booking rules incl. forced concurrency race, MCP tools + auth, HITL approve/decline, guardrail, MCP-down
- [x] Verified live: list_services → check_availability → asks name/phone → confirm card → resume → booked (shows on Bookings page)

### Phase 1 backend done
- [x] Models (businesses, documents, chunks) + Alembic migration (pgvector extension, HNSW + GIN indexes)
- [x] Ingestion: upload (PDF/TXT/MD) → background task → parse → chunk → Gemini embeddings (768-d) → pgvector
- [x] Hybrid retrieval: pgvector cosine + Postgres full-text, fused with RRF in one SQL query; `/search` debug endpoint
- [x] LangGraph graph: route (intent + standalone query rewrite) → retrieve → respond; booking placeholder branch
- [x] Postgres checkpointer (AsyncPostgresSaver + psycopg pool) → multi-turn memory; `/chat` SSE streaming; history endpoint
- [x] 13 tests (fake embedder + fake LLMs, real Postgres test DB); CI runs pgvector service
- [x] Verified live with Gemini on `samples/glow-studio-salon.md` (follow-up rewrite, refusal on unknown info, routing)

### Phase 1 frontend done
- [x] Home: list + create businesses
- [x] Workspace `/b/[id]`: document upload (multi-file), status polling while processing, delete
- [x] Streaming chat: typed SSE parser over `fetch` (POST), route badge + searched query, collapsible sources, error display
- [x] Conversation restore after reload (thread id in localStorage → history from checkpoint), "New chat"
- [x] Lint + typecheck + build pass; verified live: events `meta → route → sources → token… → done`
- [x] **SaaS redesign:** landing page; `/dashboard` app shell with sidebar (mobile drawer); businesses cards + create modal + empty state; knowledge base page (stats, drag-and-drop, status table); Playground with citation chips, suggestions, typing dots and **Agent Inspector** (route, rewritten query, sources, time-to-first-token); design system in `components/ui/` (brand gradient, light/dark tokens, Lucide icons)

## Next up
- [ ] **Review checkpoint (agreed):** walk through Phases 1–3 together, then decide the Phase 4 voice stack (cloud STT/TTS vs local models; disk space)
- [ ] Live end-to-end check through the agents once Gemini quota resets (or with a paid key)
- [ ] Human handoff / escalation path (moved to Phase 5 dashboard work)
- [ ] Dockerfiles + Compose services for API, agents and MCP (Phase 5)
- [ ] Optional demo: connect MCP Inspector / Claude Desktop to the MCP server

## Known limitations / ideas
- Chunking is character-based (1000 chars); markdown-header-aware splitting would give cleaner sections.
- Gemini streams in large chunks, so short answers arrive in 1–3 token events.
- No reranker yet (FilingLens has one) — candidate improvement with an eval set in Phase 5.
- **Gemini free tier = 20 requests/day per model** for this project; a booking conversation uses several calls. Use a paid key or wait for reset; consider model fallbacks.
- One booking at a time per business (no staff/resources yet); phone number is a lightweight ownership check (no OTP).
- MCP auth is a shared static key (production: OAuth 2.1 / per-client keys).
- A2A task stores are in memory: an `input-required` task is lost if an agent restarts (fix: `DatabaseTaskStore`).
- Booking agent only sees booking turns (its own memory).

## Before Phase 4 (agreed checkpoint)
- Review Phases 1–3 together: what was built and why.
- Decide voice stack (local models vs cloud STT/TTS APIs) **before** installing anything heavy.
  `/home` had only ~4.6 GB free on 2026-10-17; local models + PyTorch can need 2–4 GB.
  Options: cloud APIs (no PyTorch), or run local models inside Docker (root partition has ~55 GB).

## Phase checklist
- [x] Phase 0 — Setup
- [x] Phase 1 — Text core + RAG
- [x] Phase 2 — MCP
- [x] Phase 3 — A2A
- [ ] Phase 4 — Voice
- [ ] Phase 5 — Production polish

## Decision log
| Date | Decision | Reason |
|---|---|---|
| 2026-10-17 | Project = VoxDesk (voice AI agent platform for businesses) | Covers agentic/MCP/A2A/RAG/voice; real B2B use case; complements FilingLens |
| 2026-10-17 | Single monorepo `voxdesk` | One resume link, one README, one `docker compose up` |
| 2026-10-17 | Twilio dropped for now | Not needed for core demo; voice pipeline kept transport-agnostic so it can be added later |
| 2026-10-17 | pgvector over Qdrant | Postgres already needed for bookings + checkpoints; SQL tenant filtering; breadth beyond FilingLens |
| 2026-10-17 | Build own MCP server + consume via adapters | Demonstrates both sides of MCP |
| 2026-10-17 | Python 3.13 (not 3.12) | Already installed locally; 3.12 download stalled; all planned libs support 3.13 |
| 2026-10-17 | Docker host ports 5433/6380 | Local Postgres/Redis already occupy 5432/6379 |
| 2026-10-17 | Gemini `gemini-embedding-001` at 768 dims | No local model/GPU; 768 keeps index small and fast; `task_type` differs for docs vs queries |
| 2026-10-17 | Router on `gemini-2.5-flash-lite`, answers on `gemini-2.5-flash`, thinking off | Cheap/fast classification; thinking adds latency that hurts voice later |
| 2026-10-17 | Router also rewrites follow-ups into standalone search queries | One LLM call does intent + query rewrite; fixes "and how long does it take?" retrieval |
| 2026-10-17 | Thread IDs namespaced as `{business_id}:{thread_id}` | Prevents cross-tenant access to conversation checkpoints |
| 2026-10-17 | FastAPI BackgroundTasks for ingestion (not Celery yet) | Simple for now; move to a queue if uploads get large/many |
| 2026-10-17 | Frontend parses SSE manually with fetch + ReadableStream | EventSource is GET-only; chat needs POST with JSON body |
| 2026-10-17 | Thread id in localStorage, history from server checkpoint | Server is source of truth; browser only remembers which thread |
| 2026-10-17 | Poll document status (2s, only while processing) | Simple and sufficient; push (Redis pub/sub) only if needed later |
| 2026-10-17 | SaaS-style UI: landing + dashboard shell, shared `components/ui` design system | Owner wants a modern, attractive product look, not a dev tool; consistent components keep new pages cheap |
| 2026-10-17 | Gradient only for brand moments; solid indigo + shared `BRAND_TINT` elsewhere | Gradient everywhere looked busy/generic; restraint reads as more premium |
| 2026-10-17 | Agent Inspector panel with client-measured TTFT | Makes routing/retrieval visible for demos/debugging; TTFT is the key metric for voice later |
| 2026-10-17 | MCP server lives in `backend/app/mcp` (separate process), not `mcp_servers/` | Shares DB models + booking rules with the API; still deployed/run independently on :8001 |
| 2026-10-17 | Postgres exclusion constraint for bookings (btree_gist) | App checks can't stop concurrent double booking; DB guarantees it |
| 2026-10-17 | Tenant via `X-Business-Id` header on MCP connection; bearer key auth | LLM can't choose/inject another tenant; tool schemas have no business_id |
| 2026-10-17 | Stateless Streamable HTTP for MCP | Horizontal scaling; no sticky sessions |
| 2026-10-17 | HITL `interrupt()` only for write tools | Safety for real actions without confirming every lookup |
| 2026-10-17 | Code guardrail: name/phone must appear in customer messages | Gemini invented "John Doe" despite prompt rules (found in live test) |
| 2026-10-17 | Booking agent context = last 3 full turns (with tool messages) | Dropping tool results made the agent invent service ids (found in live test) |
| 2026-10-17 | Separate `date` and `time` tool args | LLMs fill these more reliably than tz-aware ISO datetimes |
| 2026-10-17 | `max_retries=2` + friendly 429 message | SDK backoff made users wait ~35 s before a generic error |
| 2026-10-18 | Agents live in `backend/app/agents` (separate processes, shared package) | Reuse RAG/booking code + models; still independently runnable on :8101/:8102 |
| 2026-10-18 | Prototype the A2A SDK before building | v1 SDK differs from tutorials; found artifact-append rule + metadata-not-persisted |
| 2026-10-18 | Supervisor keeps conversation, routing, small talk, confirmation UI | Agents stay focused; small talk avoids a network hop; UI contract unchanged |
| 2026-10-18 | Knowledge agent receives the router's standalone query | Agent can be stateless |
| 2026-10-18 | HITL = booking agent `input-required` + supervisor `interrupt()`, reply on same task | Native A2A lifecycle; survives across HTTP requests on both sides |
| 2026-10-18 | Relay agent output via LangGraph custom stream | Remote tokens/sources/tool calls reach the browser in real time |
| 2026-10-18 | Agent Card public; JSON-RPC bearer-protected (A2A_API_KEY) | Discovery is public by design; invocation needs credentials |
| 2026-10-18 | Separate liveness (`/health`) and readiness (`/health/services`) | Orchestrators restart on liveness, route traffic on readiness; one dead dependency shouldn't restart the API |
| 2026-10-17 | Commit identity = GitHub noreply email (repo-local) | Global git email is the work address; noreply links commits to yash6388 without exposing an email |
