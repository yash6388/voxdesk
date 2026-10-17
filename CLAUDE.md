# VoxDesk — context for Claude

Multi-agent **voice AI agent platform for businesses** (clinics, salons, restaurants). A business uploads its docs and services; customers talk to it (browser voice / text) to get answers (RAG) and book appointments (MCP tools). Portfolio project for an AI-engineer job switch — the owner is learning as we build, so **explain the "why" of each step** and keep code interview-explainable.

## Read first
- `docs/PLAN.md` — full plan, architecture, phases, tech decisions (source of truth)
- `docs/PROGRESS.md` — what's done, what's next, decision log. **Update it at the end of every work session.**

## Stack
- `frontend/` — Next.js (App Router, TypeScript, Tailwind)
- `backend/` — FastAPI (Python 3.13, uv), LangGraph supervisor, Gemini API
- `agents/` — A2A specialist services (knowledge_agent, booking_agent) — Phase 3
- `mcp_servers/voxdesk_mcp/` — our own FastMCP server (slots/bookings) — Phase 2
- Postgres 16 + pgvector (app data, vectors, LangGraph checkpoints), Redis, Docker Compose
  - Host ports **5433** (Postgres) and **6380** (Redis) — owner has local Postgres/Redis on the default ports for work; never use 5432/6379

## Conventions
- Backend focus is the priority; frontend stays functional and clean, not fancy.
- Async everywhere in Python; Pydantic models for all I/O; SQLAlchemy 2.0 async + Alembic.
- Config via env vars (`.env`, never committed; keep `.env.example` updated).
- Ruff for lint/format, pytest for tests. Small, focused commits.
- Don't create placeholder folders/files for future phases.

## Out of scope for now
- Twilio / phone calls (dropped; voice pipeline is transport-agnostic so it can be added later as an adapter).
