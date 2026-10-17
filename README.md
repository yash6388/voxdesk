# VoxDesk

**Multi-agent voice AI platform for businesses.** A business uploads its documents and services; customers talk to it by voice or chat. VoxDesk answers questions from the business's own knowledge base (RAG), books appointments through a custom MCP server, and delegates between specialist agents using the A2A protocol.

> 🚧 Work in progress. See [`docs/PLAN.md`](docs/PLAN.md) for the roadmap and [`docs/PROGRESS.md`](docs/PROGRESS.md) for current status.

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for diagrams (system overview, agent graph, request flows, data model).

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | Next.js, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python 3.13, uv |
| Agents | LangGraph, LangChain, Gemini |
| Protocols | MCP (FastMCP), A2A (a2a-sdk) |
| Data | PostgreSQL + pgvector, Redis |
| Voice | faster-whisper (STT) + Kokoro (TTS) locally, or ElevenLabs; WebSocket streaming |

## Project structure

```
voxdesk/
├── frontend/            Next.js app (chat, voice UI, dashboard)
├── backend/             FastAPI API + supervisor, A2A agents (app/agents), MCP server (app/mcp)
├── docs/                Plan, progress, design notes
├── samples/             Example business documents for demos and tests
└── docker-compose.yml   Postgres (pgvector) + Redis
```

## Running with Docker (everything, one command)

```bash
cp .env.example backend/.env      # add GOOGLE_API_KEY (and optionally FALLBACK_API_KEY)
docker compose --profile app up -d --build
```
Opens on http://localhost:3000 (API on :8000). The first start downloads the local voice models
(~250 MB) into a Docker volume. Seven services start: Postgres, Redis, API, MCP server, Knowledge
agent, Booking agent and the frontend. `docker compose --profile app down` stops them.

## Running locally (development)

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/), Node.js 22+

```bash
# 1. Config (add your GOOGLE_API_KEY from https://aistudio.google.com/apikey)
cp .env.example .env
cp frontend/.env.example frontend/.env.local

# 2. Infrastructure (Postgres + Redis)
docker compose up -d

# 3. Backend → http://localhost:8000 (API docs at /docs)
cd backend
uv sync
uv run alembic upgrade head       # create/upgrade database tables
uv run python -m scripts.seed_demo   # optional: demo salon with services, hours and a document
uv run python -m scripts.download_voice_models   # one-time: local speech models (~250 MB)
uv run uvicorn app.main:app --reload

# 3b. Supporting services (separate terminal): MCP server :8001,
#     Knowledge agent :8101, Booking agent :8102 — Ctrl+C stops all
cd backend
./scripts/dev_services.sh

# 4. Frontend → http://localhost:3000
cd frontend
npm install
npm run dev
```

Check everything is reachable: `curl localhost:8000/health/services` (or hover the status
indicator at the bottom of the dashboard sidebar).

## Try it (UI)

Open http://localhost:3000 → **Open dashboard** → **New business** → upload
`samples/glow-studio-salon.md` in the Knowledge base → open the **Playground** and ask
*"How much is a keratin treatment?"*, then *"And how long does it take?"*.
The **Agent Inspector** shows the routing decision, the rewritten search query, the cited sources
and the latency for each reply.

To try booking: run the seed script (or add services and hours under **Services & hours**), then in
the Playground say *"Book a men's haircut tomorrow afternoon"*. The agent checks real availability
through the MCP server, asks for your name and phone, and shows a **confirmation card** before
booking. Confirmed bookings appear on the **Bookings** page.

## Try it (voice)

Open **Voice** in a business's sidebar, allow the microphone, **hold the button** and ask a question
or book an appointment. Answers are spoken sentence by sentence; say "yes" or "no" to confirm a
booking; press the button while the agent is speaking to interrupt it. Speech runs locally
(faster-whisper + Kokoro) by default — set `TTS_PROVIDER=elevenlabs` and `ELEVENLABS_API_KEY` in
`backend/.env` for ElevenLabs voices.

## Try it (API)

With the backend running, open http://localhost:8000/docs and:
1. `POST /businesses` — create a business
2. `POST /businesses/{id}/documents` — upload `samples/glow-studio-salon.md`
3. `POST /businesses/{id}/search` — see hybrid retrieval with semantic + keyword ranks
4. `POST /chat` — ask a question; the reply streams as Server-Sent Events

## Development

```bash
cd backend
uv run pytest            # tests (needs docker compose up; uses a separate voxdesk_test DB)
uv run ruff check .      # lint
uv run ruff format .     # format
```
