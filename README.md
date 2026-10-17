# VoxDesk

**Multi-agent voice AI platform for businesses.** A business uploads its documents and services; customers talk to it by voice or chat. VoxDesk answers questions from the business's own knowledge base (RAG), books appointments through a custom MCP server, and delegates between specialist agents using the A2A protocol.

> 🚧 Work in progress. See [`docs/PLAN.md`](docs/PLAN.md) for the roadmap and [`docs/PROGRESS.md`](docs/PROGRESS.md) for current status.

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | Next.js, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python 3.13, uv |
| Agents | LangGraph, LangChain, Gemini |
| Protocols | MCP (FastMCP), A2A |
| Data | PostgreSQL + pgvector, Redis |
| Voice | Speech-to-text + text-to-speech streaming pipeline |

## Project structure

```
voxdesk/
├── frontend/            Next.js app (chat, voice UI, dashboard)
├── backend/             FastAPI gateway + LangGraph supervisor
├── docs/                Plan, progress, design notes
├── samples/             Example business documents for demos and tests
└── docker-compose.yml   Postgres (pgvector) + Redis
```

## Running locally

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
uv run uvicorn app.main:app --reload

# 4. Frontend → http://localhost:3000
cd frontend
npm install
npm run dev
```

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
