# VoxDesk — The Whole Project, Explained

> One document, end to end: what VoxDesk is, every component, how a request flows through it, the
> numbers, the trade-offs and the limitations. Read this first before an interview; the topic files
> (01–11) have the depth, `PITCH.md` has how to *say* it, `SYSTEM_DESIGN.md` has how to *scale* it.

---

## 1. What it is, in one minute

**VoxDesk is a multi-agent voice AI platform for businesses.** A salon (or clinic, restaurant…)
signs up, uploads its documents (prices, policies, FAQs), and sets its services and opening hours.
Its customers then talk to an AI agent by **voice or text** — on a public page, by QR code, or through
a chat bubble on the business's own website.

The agent can:
1. **Answer questions** from the business's own documents, with citations, and say "I don't know"
   when the documents don't cover it (**RAG**).
2. **Book, find, reschedule and cancel appointments** against real availability — and always ask
   the customer to confirm before it changes anything (**MCP tools + human-in-the-loop**).
3. **Hand the conversation to a person** when the customer wants one (**handoff → Inbox**).

The owner gets a dashboard: knowledge base, services & hours, bookings, Inbox, analytics, a share
page, and a Playground with an **Agent Inspector** that shows exactly how each reply was produced.

**Resume line:** *Multi-agent voice AI platform: a LangGraph supervisor delegates over A2A to
specialist knowledge (hybrid RAG on pgvector) and booking agents (tools via a custom MCP server),
with streaming voice, LLM failover, evals, tracing, auth and multi-tenancy.*

---

## 2. The big picture

```
                    Customers (browser: chat · voice · website widget)      Owners (dashboard)
                                   │ SSE (text)   │ WebSocket (audio)              │ REST (cookie auth)
                                   ▼              ▼                                ▼
   ┌──────────────────────────── API — FastAPI (port 8000) ─────────────────────────────────────┐
   │ guardrails · rate limits · auth · speech-to-text / text-to-speech · analytics recorder      │
   │                                                                                             │
   │  Supervisor graph (LangGraph): route ─┬─ knowledge ──► A2A ──► Knowledge agent (8101)       │
   │  memory = Postgres checkpointer       ├─ booking ────► A2A ──► Booking agent (8102)         │
   │                                       ├─ handoff (flag for staff)        │ MCP              │
   │                                       └─ respond (small talk)            ▼                  │
   └──────────────────────────────────────────────────────────────  MCP booking server (8001)  ┘
                                   │                                         │
              ┌────────────────────┴──── PostgreSQL 16 + pgvector ───────────┴──┐   Redis      Langfuse
              │ businesses · documents · chunks (vectors + full-text) · services │ (rate      (traces)
              │ hours · bookings · conversations · turns · LangGraph checkpoints │  limits)
              └──────────────────────────────────────────────────────────────────┘
```

**Five processes, one codebase** (`backend/app`): API, Knowledge agent, Booking agent, MCP server
(plus the Next.js frontend). They are deployed and scaled separately but share models, config and
domain code. Diagrams for every flow: [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

---

## 3. Following one message through the system

### 3.1 A question: *"How much is a keratin treatment?"* (text chat)

1. **Browser → `POST /chat`** with the business id, the message and a thread id.
2. **Protection first, before any LLM is paid for:** Redis rate limit (20/min per IP, 120/min per
   business) → guardrails (≤ 2,000 characters, prompt-injection patterns). Blocked → a polite reply,
   recorded as `guardrail`.
3. **Supervisor graph** (`graph/supervisor.py`), loaded with this thread's memory from the Postgres
   checkpointer:
   - `route` — a small fast model (Gemini 2.5 Flash-Lite) with **structured output** returns
     `{intent: "knowledge", search_query: "keratin treatment price"}`. The query is rewritten to stand
     alone, so a follow-up like *"and how long does it take?"* becomes *"keratin treatment duration"*.
   - `knowledge` — sends that query to the **Knowledge agent over A2A**.
4. **Knowledge agent** (`agents/knowledge.py`): **hybrid retrieval** — vector search (pgvector, HNSW,
   cosine) and keyword search (Postgres full-text, GIN) over this business's chunks only, fused with
   **Reciprocal Rank Fusion** → top 5 chunks → Gemini 2.5 Flash answers *only from those chunks* with
   `[1]`-style citations, streaming tokens back as A2A artifact chunks.
5. **Back in the API**, events are streamed to the browser as **Server-Sent Events**:
   `meta → route → delegation → sources → token… → done`. The UI renders tokens as they arrive and
   the Inspector shows route, query, sources and time-to-first-token.
6. **Recorded:** the analytics recorder saw the same events → one `turns` row (intent knowledge,
   outcome answered, first-token ms) and the conversation row updated. Langfuse has one trace spanning
   API → Knowledge agent.

### 3.2 A booking: *"Book a men's haircut tomorrow at 3, I'm Asha, 98765 43210"*

1. Route → `booking` → the supervisor delegates to the **Booking agent over A2A**.
2. The Booking agent runs its own LangGraph loop (`graph/booking_graph.py`):
   `booking_agent (LLM with tools) ⇄ tools`, with tools loaded from the **MCP server**:
   `list_services → check_availability(service, date)`.
3. When the LLM wants a **write** tool (`book_appointment`), the graph first **validates the
   arguments in code** — the customer's name and phone must actually appear in what the customer
   said (LLMs sometimes invent "John Doe") — then goes to `confirm`, which **pauses**
   (`interrupt()`). Availability and opening hours are re-checked by the booking service on the
   server when the tool runs, whatever the LLM believes.
4. Over A2A the task becomes **`input-required`**; the supervisor pauses *its* graph too and the
   browser gets a `confirm` event → a confirmation card ("Men's haircut, Tue 3:00 PM, Asha…").
5. The customer clicks **Confirm** (or says "yes" in voice) → `POST /chat/resume` → the decision goes
   back **on the same A2A task** → the tool runs → the MCP server inserts the booking.
6. **Postgres guarantees no double booking**: an exclusion constraint rejects overlapping confirmed
   bookings for the same business, even if two customers click at the same millisecond.
7. The reply includes a short reference (e.g. `DC2A71`); the booking appears on the owner's
   Bookings page; analytics records `booked`.

Why tools in a separate MCP server? The booking rules live behind a standard protocol, with their own
auth; any MCP client (our agent, Claude Desktop, an IDE) can use them. The **business id travels in
the MCP connection header**, never as a tool argument — so the LLM cannot be tricked into touching
another business.

### 3.3 A voice turn

1. The browser records while the button is held and sends the audio over a **WebSocket**
   (`/voice/{business_id}`).
2. **Speech-to-text:** faster-whisper (`base.en`, int8 on CPU; ~0.7 s for a 5.5 s utterance) — or
   ElevenLabs Scribe. Audio is decoded with PyAV directly.
3. The transcript goes through **the same guardrails and the same supervisor graph** as chat
   (`conversation.py` is transport-independent).
4. **Sentence-by-sentence speech:** as tokens stream in, a sentence splitter cuts complete sentences
   and sends each to text-to-speech (Kokoro int8 ONNX, ~0.47× real time on a laptop CPU — or
   ElevenLabs Flash) **while the LLM is still writing the next one**. The caller hears the first
   sentence long before the full answer exists. The key metric is **time to first audio**.
5. Booking confirmation can be **spoken** ("yes" / "no" are recognised) or clicked. Pressing the
   button while the agent speaks **interrupts** it (barge-in = cancelling the running task).
6. Each turn reports `stt_ms`, `first_token_ms`, `first_audio_ms`, `total_ms` on the Voice page.

### 3.4 *"I want to speak to the manager"*

Route → `handoff` → a fixed reply ("I've let the team know… please share your name and number") plus
a `handoff` event → the conversation becomes `needs_human` → it appears in the owner's **Inbox** with
its transcript (read from the checkpoint) until someone clicks **Mark resolved**. A rule in code stops
the next message (usually the contact details) from being handed off again — found in live testing.

---

## 4. Components, one by one

| Component | Where | What it does | Key decision |
|---|---|---|---|
| **API** | `app/main.py`, `app/api/*` | REST for owners, SSE chat, WebSocket voice, health | FastAPI + async everywhere; one lifespan opens agent clients, checkpointer, voice models |
| **Supervisor graph** | `app/graph/supervisor.py` | Routing, memory, delegation, human-in-the-loop pause, handoff | Explicit state machine (not a free-roaming agent): predictable, testable |
| **Router** | `classify()` | Intent + standalone search query in one structured-output call | Cheapest model; 100% on the routing eval |
| **Knowledge agent** | `app/agents/knowledge.py`, `app/rag/*` | Hybrid retrieval + grounded, cited answer | Stateless: receives the already-rewritten query |
| **Booking agent** | `app/agents/booking.py`, `graph/booking_graph.py` | Tool-calling loop with confirmation before writes | Checks customer details are real (not invented) before asking the human |
| **MCP server** | `app/mcp/server.py` | 7 tools: business info, services, availability, book, find, reschedule, cancel | Tenant from connection header; bearer key; stateless HTTP |
| **Booking rules** | `app/booking/service.py` | Availability, opening hours, timezones, overlaps | Shared by MCP server and owner REST API — one source of truth |
| **A2A layer** | `app/a2a/*` | Agent Cards, task lifecycle, streaming artifacts, input-required | Business info sent as metadata on every message (A2A doesn't persist it) |
| **Ingestion** | `app/rag/ingestion.py` | PDF/MD/TXT → text → 500-char chunks (100 overlap) → 768-d embeddings | Chunk size chosen by the eval suite |
| **Voice** | `app/voice/*`, `app/api/voice.py` | STT, sentence splitter, TTS, barge-in | Local by default (free, private), ElevenLabs by config |
| **LLM layer** | `app/llm.py`, `app/circuit_breaker.py` | Gemini + OpenAI-compatible fallback, circuit breaker | Failover in ~0.5 s instead of ~2.3 s; no embedding fallback |
| **Auth** | `app/auth.py` | Argon2id, JWT in httpOnly cookie, owner-only routers | Other tenants get **404** (no id enumeration) |
| **Protection** | `app/ratelimit.py`, `app/guardrails.py` | Redis fixed-window limits, input guardrails | Fail open on Redis outage; guardrails before any LLM cost |
| **Tracing** | `app/tracing.py` | Langfuse traces per turn, continued across A2A | Distributed tracing: trace ids in A2A metadata |
| **Analytics** | `app/analytics.py`, `app/api/insights.py` | Turn outcomes, Inbox, analytics SQL | Derived from the event stream; transcripts from the checkpoint |
| **Evals** | `backend/evals/` | Golden set, retrieval/routing/answers/booking, LLM judge | Uses production functions; temporary business per run |
| **Frontend** | `frontend/` | Landing, auth, dashboard, Playground + Inspector, voice, share, widget | Typed API client; SSE parsed manually (POST) |
| **Widget** | `frontend/public/widget.js` | One `<script>` → chat bubble → iframe to `/c/<slug>?embed=1` | Iframe isolation; frame-deny headers on every other page |

---

## 5. Data model (short version)

- `users` → own `businesses` (unique `slug` for the public page, timezone, currency).
- `documents` → `chunks` (text, `vector(768)` with HNSW index, generated `tsvector` with GIN index,
  `business_id` on every row for tenant filtering).
- `services`, `business_hours`, `bookings` (exclusion constraint: no overlapping confirmed bookings).
- `conversations` (one per thread; open / needs_human / resolved) → `turns` (intent, outcome,
  previews, latency).
- LangGraph checkpoint tables (managed by LangGraph) hold every conversation's full state.

Everything is in **one Postgres**: app data, vectors, agent memory. One backup, one connection
string, SQL joins between vectors and business data. Full ER diagram in `ARCHITECTURE.md`.

---

## 6. The numbers

| What | Result |
|---|---|
| Retrieval, hybrid @ 500-char chunks | **Hit@1 86% · Hit@3 100% · MRR 0.93** (vector 82%, keyword 77%) |
| Same at 1000-char chunks (equal overlap) | Hit@1 82% · MRR 0.90 → **switched production to 500** |
| Intent routing (16 cases, 4 intents) | **100%**, p50 ~0.5 s |
| Fact accuracy / faithfulness (LLM judge) | **100% / 5.0 of 5** |
| Correct refusal on unanswerable questions | **100%** |
| Booking agent task success (5 scenarios, fake tools) | **100%** |
| Backend tests | **130**, against real Postgres, fake LLMs |
| Whisper STT (base.en, CPU) | ~0.7 s for a 5.5 s utterance |
| Kokoro TTS (int8, CPU) | ~0.47× real time (2.6 s for 5.5 s of audio) |
| Gemini 429 → fallback | ~0.5 s (was ~2.3 s with retries) |
| Docker images | backend 1.6 GB (speech runtimes), frontend 243 MB |

Honesty notes: evaluation latencies on free tiers include rate-limit waits (Groq's per-minute token
cap; a single call is ~0.3 s), so eval p95 is not product latency. The golden set is small (≈50
cases) — good for catching regressions and making decisions, not a statistically strong benchmark.

---

## 7. Key trade-offs (and what I'd say about them)

| Choice | Alternative | Why this |
|---|---|---|
| Explicit LangGraph graph | One ReAct agent with all tools | Predictable routing, testable nodes, built-in checkpoints/interrupts/streaming |
| Specialists as A2A services | Everything in one process | Independent deploy/scale, failure isolation, least privilege; cost = network hop + complexity |
| Own MCP server | Tools as Python functions | Decoupled, reusable by any MCP client, separate auth; tenant can't be chosen by the LLM |
| pgvector in main Postgres | Pinecone/Qdrant | One database, SQL tenant filters, transactions; fine to millions of chunks |
| Hybrid + RRF | Vector only | Names/prices/codes need keyword match; RRF needs no score normalisation; measured +4 pts Hit@1 |
| Confirmation only for write tools | Confirm everything | Safety where it matters, no confirmation fatigue |
| Validate tool args in code | Trust the prompt | LLMs sometimes ignore rules; invariants belong in code |
| Exclusion constraint | Check-then-insert in Python | Only the database can prevent races |
| Local STT/TTS default | Cloud APIs only | Free, private, no quotas; same interface switches to ElevenLabs |
| Sentence-level TTS pipelining | Synthesize the full answer | Time-to-first-audio drops to roughly first sentence |
| Gemini + fallback + breaker | Single provider | Free-tier 429s were real; breaker skips a dead provider instantly |
| JWT in httpOnly cookie | Token in localStorage | JavaScript (and XSS) can't read it |
| 404 for other tenants | 403 | Doesn't reveal that an id exists |
| Fail-open rate limiter | Fail-closed | A Redis blip shouldn't take customer conversations down |
| Analytics from event stream | Instrument every node | One recorder for chat and voice; agents unaware |

---

## 8. Bugs and lessons (the best interview stories)

1. **Double counting in the circuit breaker** — nested wrappers both counted one failure; tests caught
   it, fixed with a context variable.
2. **A2A streaming** — the first artifact chunk must use `append=False`, or clients drop the text.
3. **A2A metadata isn't persisted** across messages of a task → business info sent on every message.
4. **PyAV incompatibility** — faster-whisper's audio helper broke on PyAV 19 → decode with PyAV
   directly.
5. **Confounded experiment** — my first chunk-size comparison also changed the overlap and showed a
   13-point gap; the controlled comparison showed 4. Reported the honest number.
6. **Mislabelled golden case** — the agent was right and my label was wrong; evaluate the evaluator.
7. **Full-width citations** `【1】` from the fallback model broke TTS and the UI → handled in both,
   prompt tightened.
8. **Timezone mismatch** in daily analytics (SQL local dates vs Python UTC "today").
9. **Repeat handoff** — the router kept routing the customer's contact details to handoff; a prompt
   fix didn't hold; a deterministic rule did.
10. **Golden set never committed** — a `data/` ignore rule (for voice models) also matched
    `evals/data/`; found while reviewing the diff.

Common thread: **enforce invariants in code, measure before claiming, and test live — fakes only
test what you scripted.**

---

## 9. Limitations (say them before they're asked)

- **No phone calls** yet (Twilio dropped for scope); the voice pipeline is transport-agnostic, so a
  telephony adapter is the next step.
- **Push-to-talk**, not continuous conversation: no voice-activity detection or streaming STT yet.
- **One calendar per business** — no per-staff or per-room resources.
- **Handoff = flag + Inbox**; no live human takeover or notifications (email/WhatsApp) yet.
- **A2A tasks are kept in memory** in each agent: restarting the booking agent mid-confirmation loses
  that pending booking, and booking agents can't run as multiple replicas until tasks move to a
  database-backed store.
- **Small golden set**; no reranker yet (planned experiment).
- **Not deployed yet** — the repo is deploy-ready (Docker images, health checks, production safety
  checks), target to be chosen.
- Free-tier LLM quotas make latency variable; production would use paid tiers.

---

## 10. Where to go next in these notes

| Want to… | Read |
|---|---|
| Present the project | [`PITCH.md`](PITCH.md) |
| Answer "design this at scale" | [`SYSTEM_DESIGN.md`](SYSTEM_DESIGN.md) |
| Practise questions | [`QA_BANK.md`](QA_BANK.md) |
| Go deep on one area | `01`–`11` in [`00_INDEX.md`](00_INDEX.md) |
