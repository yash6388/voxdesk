# VoxDesk — Progress Log

> Update at the end of every work session: tick tasks, set "Next up", add decisions.

## Current status
**Phase 1 — Text core + RAG** · backend ✅ done, frontend next

### Phase 0 done
- [x] GitHub repo `yash6388/voxdesk` created, remote connected
- [x] `backend/`: FastAPI app factory, `/health`, pydantic-settings config, ruff + pytest (1 test passing)
- [x] `frontend/`: Next.js 15 + Tailwind, home page with live backend status
- [x] `docker-compose.yml`: Postgres 16 + pgvector 0.8.7, Redis 7 (verified running)
- [x] `.gitignore`, `.env.example`, README
- [x] GitHub Actions CI (backend lint+test, frontend lint+build)

### Phase 1 backend done
- [x] Models (businesses, documents, chunks) + Alembic migration (pgvector extension, HNSW + GIN indexes)
- [x] Ingestion: upload (PDF/TXT/MD) → background task → parse → chunk → Gemini embeddings (768-d) → pgvector
- [x] Hybrid retrieval: pgvector cosine + Postgres full-text, fused with RRF in one SQL query; `/search` debug endpoint
- [x] LangGraph graph: route (intent + standalone query rewrite) → retrieve → respond; booking placeholder branch
- [x] Postgres checkpointer (AsyncPostgresSaver + psycopg pool) → multi-turn memory; `/chat` SSE streaming; history endpoint
- [x] 13 tests (fake embedder + fake LLMs, real Postgres test DB); CI runs pgvector service
- [x] Verified live with Gemini on `samples/glow-studio-salon.md` (follow-up rewrite, refusal on unknown info, routing)

## Next up
- [ ] Phase 1 frontend: business create/select, document upload + status, streaming chat UI with sources
- [ ] Then Phase 2 (MCP booking server)

## Known limitations / ideas
- Chunking is character-based (1000 chars); markdown-header-aware splitting would give cleaner sections.
- Gemini streams in large chunks, so short answers arrive in 1–3 token events.
- No reranker yet (FilingLens has one) — candidate improvement with an eval set in Phase 5.

## Before Phase 4 (agreed checkpoint)
- Review Phases 1–3 together: what was built and why.
- Decide voice stack (local models vs cloud STT/TTS APIs) **before** installing anything heavy.
  `/home` had only ~4.6 GB free on 2026-10-17; local models + PyTorch can need 2–4 GB.
  Options: cloud APIs (no PyTorch), or run local models inside Docker (root partition has ~55 GB).

## Phase checklist
- [x] Phase 0 — Setup
- [ ] Phase 1 — Text core + RAG
- [ ] Phase 2 — MCP
- [ ] Phase 3 — A2A
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
| 2026-10-17 | Commit identity = GitHub noreply email (repo-local) | Global git email is the work address; noreply links commits to yash6388 without exposing an email |
