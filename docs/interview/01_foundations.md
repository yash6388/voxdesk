# 01 — Foundations: Repo, Tooling, Infrastructure, Migrations, CI

> Covers Phase 0 and the infrastructure parts of Phase 1. None of this is "AI", but interviewers
> use it to judge whether you build like a professional engineer or like a tutorial follower.

---

## 1. Monorepo structure

**Plain English:** everything (frontend, backend, later the agents and the MCP server) lives in one
Git repository called `voxdesk`.

```
voxdesk/
├── frontend/            Next.js app
├── backend/             FastAPI + LangGraph
├── docs/                plan, progress, these interview notes
├── samples/             demo business documents
├── docker-compose.yml   Postgres (pgvector) + Redis
└── .github/workflows/   CI
```

**Why a monorepo?**
- One link to share, one README, one `docker compose up`.
- A change that touches both API and UI is one commit, so history stays consistent.
- Later (Phase 3) the A2A agents become separate *services*, but they still live in the same repo —
  "separate deployables, one repo" is a common real-world setup.

**Say it like this:**
> "It's a monorepo with independently runnable services — Next.js frontend, FastAPI backend, and
> later separate agent services. One repo keeps changes atomic across the stack, while each service
> can still be deployed on its own."

---

## 2. Python tooling: uv, pyproject.toml, uv.lock

**Plain English:** `uv` is a modern, very fast replacement for `pip` + `venv` + `requirements.txt`.

| File | What it holds |
|---|---|
| `backend/pyproject.toml` | The packages *we asked for* (e.g. `fastapi>=0.143`), plus tool config (ruff, pytest) |
| `backend/uv.lock` | The *exact* version of every package, including dependencies of dependencies |
| `backend/.venv/` | The virtual environment (created automatically, not committed) |

**Why the lock file matters:** without it, `fastapi>=0.143` could install a different version next
month and break something. With `uv sync --locked`, your laptop, CI and production all install
byte-identical dependencies → "works on my machine" problems disappear.

**Commands to know:** `uv add <pkg>` (install + record), `uv sync` (install from lock),
`uv run <cmd>` (run inside the venv without activating it).

**Detail worth mentioning:** `google-genai` is listed explicitly even though
`langchain-google-genai` already pulls it in — because our code imports it directly
(`app/rag/embeddings.py`). Never rely on a package that's only there transitively.

---

## 3. Configuration: pydantic-settings and `.env`

**File:** `backend/app/config.py`

**Plain English:** all settings (database URL, API key, model names, chunk size…) live in one
`Settings` class. Values come from environment variables, or from a `.env` file in development.

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://...:5433/voxdesk"
    google_api_key: str = ""
    chat_model: str = "gemini-2.5-flash"
    chunk_size: int = 1000
    ...
```

**Why this design:**
- **12-Factor App principle:** config lives in the environment, not in code. The same Docker image
  runs in dev, staging and prod with different env vars.
- **Secrets never committed:** `.env` is in `.gitignore`; `.env.example` (committed) documents
  which variables exist without real values.
- **Type-checked:** pydantic validates types at startup — a typo like `CHUNK_SIZE=abc` fails
  immediately instead of crashing later.
- `@lru_cache` on `get_settings()` → settings are parsed once and reused.

---

## 4. Docker Compose: Postgres + pgvector, Redis

**File:** `docker-compose.yml`

**Plain English:** instead of installing Postgres and Redis on the laptop, they run in Docker
containers defined in a file. `docker compose up -d` starts both.

```yaml
postgres:
  image: pgvector/pgvector:pg16      # Postgres 16 with pgvector preinstalled
  ports: ["${POSTGRES_HOST_PORT:-5433}:5432"]
  volumes: [postgres_data:/var/lib/postgresql/data]   # data survives restarts
  healthcheck: pg_isready ...
```

**Points worth explaining:**
- **Port mapping `5433:5432`** — the laptop already had a local Postgres on 5432, so the container
  is exposed on 5433. Shows you understand host vs container ports.
- **Named volume** — the database files live in a Docker volume, so `docker compose down` keeps the
  data; `down -v` deletes it.
- **Healthchecks** — Docker knows when Postgres is actually ready to accept connections, not just
  "container started".

**Say it like this:**
> "All infrastructure is declared in Docker Compose, so anyone can start the full stack with one
> command and get the same versions I use. The same pgvector image is used in CI."

---

## 5. Database access: async SQLAlchemy 2.0

**Files:** `backend/app/db/session.py`, `backend/app/db/models.py`

**Plain English:** SQLAlchemy maps Python classes to database tables. We use the **async** version
(with the `asyncpg` driver) so a request waiting for the database doesn't block other requests.

```python
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_session():          # FastAPI dependency: one session per request
    async with SessionLocal() as session:
        yield session
```

- `pool_pre_ping=True` — checks a pooled connection is alive before using it (survives DB restarts).
- `expire_on_commit=False` — objects stay readable after commit (needed when returning them as API
  responses in async code).
- **Dependency injection:** endpoints declare `session: SessionDep` (defined in `app/api/deps.py`
  using `Annotated`). FastAPI creates and closes the session automatically, and tests can swap
  dependencies (e.g. replace the real embedder with a fake).

**A real bug we hit (good story):** in a test, accessing `business.documents` triggered SQLAlchemy's
*lazy loading* — a hidden database query. In async SQLAlchemy that's not allowed and raises
`MissingGreenlet`. Fix: load related data with an explicit `select(...)`. Lesson: in async ORM code,
all I/O must be explicit and awaited.

---

## 6. Alembic migrations

**Folder:** `backend/alembic/`

**Plain English:** a migration is a versioned Python script that changes the database schema
(create table, add column, add index). Alembic tracks which migrations have run in an
`alembic_version` table. `uv run alembic upgrade head` brings any database up to date.

**Why not just `create_all()`?** `create_all` only creates missing tables — it can't add a column to
an existing table or roll back. Migrations give you a reviewable, reversible history of schema
changes, which is mandatory once there's real data.

**Our workflow:**
1. Change models in `app/db/models.py`
2. `uv run alembic revision --autogenerate -m "describe change"` → Alembic diffs models vs DB
3. **Review and fix the generated file** (autogenerate is a draft, not gospel)
4. `uv run alembic upgrade head`; test `downgrade` too

**Three manual fixes we made to the first migration (great to mention):**
1. Added `CREATE EXTENSION IF NOT EXISTS vector` — a fresh database doesn't know the `vector` type.
2. Added the missing `import pgvector.sqlalchemy` (and to the template for future migrations).
3. Downgrade drops the `document_status` enum type — otherwise re-running upgrade fails.

**A subtle trap we avoided:** LangGraph creates its *own* checkpoint tables. Alembic autogenerate
would see them as "tables not in the models" and generate `DROP TABLE` for them. `env.py` has an
`include_name` filter so Alembic only manages our tables.

**Say it like this:**
> "Schema changes go through Alembic migrations, which I review rather than trust blindly — for
> example autogenerate didn't add the pgvector extension, and it would have dropped LangGraph's
> checkpoint tables, so I added a filter in env.py to scope it to our models."

---

## 7. Linting and formatting: ruff

**Config:** `[tool.ruff]` in `backend/pyproject.toml`

Ruff is a very fast linter + formatter (replaces flake8, isort, black). Rule sets enabled:
`E/F` (errors, pyflakes), `I` (import sorting), `UP` (modern Python syntax), `B` (bugbear — likely
bugs), `ASYNC` (async mistakes like blocking calls in async functions).

**Example of ruff improving the code:** rule `B008` flagged `session = Depends(get_session)` in
function defaults. We refactored to the modern FastAPI style:
```python
SessionDep = Annotated[AsyncSession, Depends(get_session)]
async def list_businesses(session: SessionDep): ...
```
Cleaner, reusable, and type-checker friendly.

---

## 8. CI with GitHub Actions

**File:** `.github/workflows/ci.yml`

**Plain English:** on every push and pull request, GitHub spins up fresh machines and runs:

| Job | Steps |
|---|---|
| backend | start a **pgvector Postgres service container** → `uv sync --locked` → `ruff check` + `ruff format --check` → `pytest` |
| frontend | `npm ci` → `npm run lint` → `npm run build` |

**Why it matters:** broken code shows a red ❌ on the commit before anyone deploys it. The backend
job runs tests against a *real* Postgres with pgvector (same image as local), so the hybrid-search
SQL is actually tested, not mocked.

**Say it like this:**
> "Every push runs lint, formatting checks, tests against a real pgvector Postgres service
> container, and a production build of the frontend, with locked dependencies so CI matches local."

---

## Q&A

**Q: Why FastAPI over Flask or Django?**
A: It's async-first, which suits I/O-heavy work like LLM and database calls; it validates
requests/responses with Pydantic; and it generates OpenAPI/Swagger docs automatically. Django is
great for full-stack CRUD apps but heavier than we need for an API service.

**Q: Why async at all?**
A: Most time in this app is spent *waiting* — on Gemini, on Postgres. Async lets one process serve
many requests concurrently during those waits, instead of one thread per request.

**Q: What's the difference between `pyproject.toml` and `uv.lock`?**
A: pyproject lists direct dependencies with version ranges; the lock file pins exact versions of
the entire dependency tree so installs are reproducible.

**Q: How do you handle secrets?**
A: Environment variables, loaded by pydantic-settings. `.env` is gitignored; `.env.example`
documents the variables. In production they'd come from the platform's secret store.

**Q: What happens if a migration fails halfway?**
A: Postgres supports transactional DDL, so Alembic runs each migration in a transaction — a failure
rolls back cleanly (you can see "Will assume transactional DDL" in Alembic's output).

**Q: Why expose Postgres on 5433?**
A: The host already had a Postgres on 5432. Host port and container port are independent; the
container still listens on 5432 internally.
