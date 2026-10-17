# VoxDesk — context for Claude

Multi-agent **voice AI agent platform for businesses** (clinics, salons, restaurants). A business uploads its docs and services; customers talk to it (browser voice / text) to get answers (RAG) and book appointments (MCP tools). Portfolio project for an AI-engineer job switch — the owner is learning as we build, so **explain the "why" of each step** and keep code interview-explainable.

## Read first
- `docs/PLAN.md` — full plan, architecture, phases, tech decisions (source of truth)
- `docs/PROGRESS.md` — what's done, what's next, decision log. **Update it at the end of every work session.**
- `docs/ARCHITECTURE.md` — living architecture doc with Mermaid diagrams (overview, deployment, components, agent graph, sequence flows, ER model). **Update it after each phase** (flip planned → built, add new flows/tables).
- `docs/interview/` — beginner-friendly interview notes. **After each phase, add/update the topic file** (see `00_INDEX.md`): plain English → how it works (with file refs) → why/trade-offs → real results → limitations → Q&A. `PROJECT_EXPLAINED.md`, `PITCH.md` and `SYSTEM_DESIGN.md` are written only at the very end.

## Stack
- `frontend/` — Next.js (App Router, TypeScript, Tailwind)
- `backend/` — FastAPI (Python 3.13, uv), LangGraph supervisor, Gemini API
- `backend/app/agents/` — A2A specialist services: knowledge (:8101), booking (:8102); `backend/app/a2a/` — A2A server/client helpers
- `backend/app/graph/` — `supervisor.py` (API graph), `booking_graph.py` (runs in booking agent)
- `backend/scripts/dev_services.sh` — starts MCP + both agents; API runs separately
- `backend/app/voice/` + `app/api/voice.py` — voice WebSocket; STT/TTS providers (`STT_PROVIDER`/`TTS_PROVIDER`: local | elevenlabs); models via `uv run python -m scripts.download_voice_models` (gitignored `backend/data/models`)
- `backend/app/mcp/` — our own FastMCP booking server, run separately: `uv run python -m app.mcp.server` (:8001)
- `backend/app/booking/` — booking domain rules (shared by MCP server + owner REST API)
- `backend/scripts/seed_demo.py` — demo salon data (`uv run python -m scripts.seed_demo`)
- `backend/app/llm.py` — all chat models (Gemini behind a circuit breaker; OpenAI-compatible fallback — Groq/OpenRouter/HF — when `FALLBACK_API_KEY` is set; `LLM_PRIMARY=fallback` flips the order)
- Postgres 16 + pgvector (app data, vectors, LangGraph checkpoints), Redis, Docker Compose
  - Host ports **5433** (Postgres) and **6380** (Redis) — owner has local Postgres/Redis on the default ports for work; never use 5432/6379

## Conventions
- Backend focus is the priority; frontend stays functional and clean, not fancy.
- Async everywhere in Python; Pydantic models for all I/O; SQLAlchemy 2.0 async + Alembic.
- Config via env vars (`.env`, never committed; keep `.env.example` updated).
- Ruff for lint/format, pytest for tests. Small, focused commits.
- Don't create placeholder folders/files for future phases.
- The owner often has `uvicorn --reload` (:8000) and `next dev` (:3000) running. Check ports before starting servers, and **never run `npm run build` while `next dev` is running** (both write `.next/` and break the dev server).
- Never run `git commit`/`git push` — give the owner the commands instead.

## Out of scope for now
- Twilio / phone calls (dropped; the voice pipeline is transport-agnostic so it can be added later as an adapter).
