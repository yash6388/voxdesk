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
└── docker-compose.yml   Postgres (pgvector) + Redis
```

## Running locally

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/), Node.js 22+

```bash
# 1. Config
cp .env.example .env
cp frontend/.env.example frontend/.env.local

# 2. Infrastructure (Postgres + Redis)
docker compose up -d

# 3. Backend → http://localhost:8000 (API docs at /docs)
cd backend
uv sync
uv run uvicorn app.main:app --reload

# 4. Frontend → http://localhost:3000
cd frontend
npm install
npm run dev
```

## Development

```bash
cd backend
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
```
