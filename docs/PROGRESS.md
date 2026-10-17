# VoxDesk — Progress Log

> Update at the end of every work session: tick tasks, set "Next up", add decisions.

## Current status
**Phase 0 — Setup ✅ done** · next: Phase 1

### Phase 0 done
- [x] GitHub repo `yash6388/voxdesk` created, remote connected
- [x] `backend/`: FastAPI app factory, `/health`, pydantic-settings config, ruff + pytest (1 test passing)
- [x] `frontend/`: Next.js 15 + Tailwind, home page with live backend status
- [x] `docker-compose.yml`: Postgres 16 + pgvector 0.8.7, Redis 7 (verified running)
- [x] `.gitignore`, `.env.example`, README
- [x] GitHub Actions CI (backend lint+test, frontend lint+build)

## Next up
- [x] First commit pushed, CI green
- [ ] Phase 1: DB models + Alembic migrations (business, document, chunk, conversation)

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
| 2026-10-17 | Commit identity = GitHub noreply email (repo-local) | Global git email is the work address; noreply links commits to yash6388 without exposing an email |
