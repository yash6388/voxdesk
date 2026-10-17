# 04 — Testing Strategy

> Phase 1. How do you test an app whose core is a non-deterministic, paid, external LLM?

---

## 1. Plain English first

LLM calls are **slow, cost money, need an API key, and give slightly different answers each time**.
If tests called Gemini, they'd be flaky and couldn't run in CI without secrets.

So we split the problem:
- **Our code** (routing logic, retrieval SQL, ingestion, API behaviour, memory) → tested
  automatically with **fakes** for the LLM and embeddings, against a **real Postgres**.
- **The LLM's quality** (are answers correct and grounded?) → tested separately with an
  **evaluation set** (Phase 5), not in unit tests.

Result: **13 tests, ~1 second, no API key, deterministic**, running in CI on every push.

---

## 2. The fakes

**File:** `backend/tests/conftest.py`, `backend/tests/test_graph.py`

### FakeEmbedder
```python
class FakeEmbedder:
    def _vec(self, text):
        # bag-of-words: hash each word into one of 768 slots, then normalise
```
Texts that share words get similar vectors — enough to make semantic search behave sensibly in tests
without calling Gemini. It satisfies the same `Embedder` Protocol as `GeminiEmbedder`, which is why
designing to an interface paid off.

### Fake LLMs
- **Chat model:** LangChain's `GenericFakeChatModel` returns scripted replies and even supports
  streaming.
- **Router:** a tiny `FakeRouter` whose `with_structured_output()` returns pre-scripted `Route`
  decisions. This lets a test say "pretend the router chose `booking`" and check the graph does the
  right thing next.

### Dependency overrides (API tests)
```python
app.dependency_overrides[get_embedder] = lambda: fake_embedder
```
FastAPI's dependency injection lets tests replace the real embedder without touching app code.

---

## 3. Why a real Postgres instead of mocking the database?

The most important logic is **SQL** — the hybrid search with RRF, pgvector distance, full-text
matching, cascading deletes. Mocking the database would test nothing real. So:
- Tests use a separate database `voxdesk_test` (created automatically by a session fixture).
- Tables are created once per run; each test starts by `TRUNCATE`-ing them, so tests are independent.
- In CI, GitHub Actions starts the **same `pgvector/pgvector:pg16` image** as a service container.

---

## 4. What's covered

| Test file | What it proves |
|---|---|
| `test_health.py` | App starts, `/health` works |
| `test_rag.py` | Chunking respects size; ingestion marks documents `ready`; empty documents fail gracefully with an error; hybrid search ranks the relevant chunk first (keyword rank 1); **tenant isolation** — one business never retrieves another's chunks |
| `test_graph.py` | Knowledge intent → retrieve → respond fills context; booking intent skips the LLM and returns the placeholder; **memory** — two turns on the same thread accumulate 4 messages |
| `test_api.py` | Upload → background ingestion → `ready` → searchable; `.md` sent as `octet-stream` accepted; unsupported type → 415; unknown business → 404 |

---

## 5. Bugs the tests caught (good stories)

1. **`MissingGreenlet` in async SQLAlchemy** — a test touched `business.documents`, triggering a
   hidden lazy-load query, which async SQLAlchemy forbids. Fixed with an explicit `select`.
   Lesson: in async ORM code, all I/O must be explicit.
2. **Event-loop mismatch** — the app's database engine is a module-level singleton, but pytest gave
   each test a new event loop, so pooled connections belonged to a dead loop. Fixed by running all
   tests on one session-scoped loop (`asyncio_default_test_loop_scope = "session"`).
3. **Message de-duplication** — the fake LLM returned the *same message object* twice; LangGraph's
   `add_messages` reducer de-duplicates by ID, so the second reply replaced the first. Understanding
   the reducer explained it; the fake now creates a fresh message per reply.

---

## 6. What's *not* covered yet (honest gaps)

- LLM answer quality, routing accuracy, retrieval hit rate → **evaluation suite in Phase 5**
  (golden question set, hit-rate@k, faithfulness checks).
- The SSE endpoint end-to-end with a fake graph.
- Load/performance tests.
- Frontend tests.

---

## Q&A

**Q: How do you test LLM applications?**
A: Two layers. Deterministic tests for everything around the LLM — with fake models, real
database — run in CI on every push. And an evaluation suite for the LLM behaviour itself: a golden
dataset of questions with expected sources/answers, measured with metrics like hit-rate and
faithfulness, run when prompts, models or retrieval change.

**Q: Why not mock the database?**
A: The core logic is SQL (hybrid search, vector distance, full-text). Mocks would only test that I
call the mock. A real pgvector Postgres in Docker is fast and is exactly what production runs.

**Q: How do you keep tests independent?**
A: Separate test database, schema created once, tables truncated before each test, no shared
state between tests.

**Q: Unit vs integration tests here?**
A: `test_split_text` is a pure unit test. Most others are integration tests (real DB, faked
external APIs) — for this kind of app they give far more confidence per test.
