# VoxDesk — System Design Round Guide

> How to answer *"Design a voice AI agent platform for businesses"* (or "design a RAG chatbot",
> "design an AI booking assistant") using VoxDesk as the backbone. Follows the standard interview
> structure: **requirements → estimates → high-level design → deep dives → data model → scaling →
> failures → trade-offs**, then a minute-by-minute whiteboard script.
>
> Golden rule: say clearly which parts **VoxDesk does today** and which are **how I'd scale it**.
> Interviewers reward the honesty and the reasoning, not a bigger diagram.

---

## 1. Clarify requirements (first 3–5 minutes)

Ask, then write the answers on the board.

**Functional**
1. Businesses sign up, upload documents, configure services and opening hours.
2. Customers talk to the business's agent by **text and voice** (browser; phone later).
3. The agent answers from the business's documents (grounded, cited, refuses when unsure).
4. The agent books / reschedules / cancels appointments against real availability, with customer
   confirmation before any change.
5. Escalation to a human; owner sees transcripts, bookings and analytics.

**Non-functional**
| Requirement | Target | Why |
|---|---|---|
| Voice responsiveness | time to first audio **< 1.5 s** after the customer stops talking | Silence on a call feels broken |
| Text responsiveness | first token **< 1 s** | Streaming makes it feel instant |
| Correctness of bookings | **zero double bookings**, no booking without confirmation | Real-world side effects |
| Tenant isolation | a business can never see or affect another's data | Multi-tenant SaaS basics |
| Availability | 99.9 % for customer conversations; degrade gracefully | Questions should work even if booking is down |
| Cost | LLM spend per conversation bounded per tenant | LLM calls are the main cost |

**Out of scope (say it):** payments, staff scheduling across multiple resources, phone telephony
(design the seam for it), multilingual (mention as extension).

---

## 2. Back-of-the-envelope estimates (state assumptions out loud)

**Assumptions:** 10,000 businesses · 100 conversations per business per day · 4 customer turns per
conversation · 30 % of turns are voice · peak = 5× average.

| Quantity | Estimate |
|---|---|
| Turns per day | 10k × 100 × 4 = **4 M/day** |
| Average / peak turns per second | 4 M / 86,400 ≈ **46/s** → peak **~230/s** |
| LLM calls per turn | router + answer = 2 (booking turns 3–6) → peak **~500–1,000 LLM calls/s** |
| Tokens per turn | router ~800 in, answer ~2,000 in + ~150 out → **~3k tokens** → **~12 B tokens/day** |
| Voice audio | 1.2 M voice turns × ~5 s = 6 M audio-seconds/day → avg ~70, peak **~350 concurrent streams** |
| Chunks stored | 10k × 50 docs × 40 chunks = **20 M chunks** |
| Vector storage | 20 M × 768 × 4 B ≈ **61 GB** raw (+ HNSW index ≈ 2×) → ~150 GB; `halfvec` halves it |
| Turn analytics rows | 4 M/day × ~1.5 KB ≈ **6 GB/day** → partition by month, keep 90 days hot |

**What the numbers tell you (say this — it's the point of estimating):**
- The **LLM is the bottleneck and the cost**, not our servers. ~230 turns/s of API work is small for
  a handful of async FastAPI pods; ~1,000 LLM calls/s needs provider quota planning, per-tenant
  budgets, caching and a cheap model for routing.
- **Speech is the second hot spot**: CPU Whisper handles roughly a few real-time streams per core;
  at ~350 concurrent streams you want GPU workers or a streaming STT API.
- **Postgres + pgvector is fine** at 20 M chunks with HNSW, especially because every query filters by
  one business (small candidate sets).

---

## 3. High-level design

```
 Clients ── browser chat (SSE) · browser voice (WebSocket) · website widget · [phone adapter]
    │
    ▼
 Load balancer / CDN (static frontend)
    │
 API tier (stateless FastAPI pods)
   · auth · rate limits · guardrails · session WebSockets
   · Supervisor graph (LangGraph) — state in checkpoint store
    │                 │                     │
    │ A2A             │ A2A                 │ queue
    ▼                 ▼                     ▼
 Knowledge agents   Booking agents ── MCP ──► Booking tool servers ──► Postgres (bookings)
 (stateless pods)   (stateless pods)
    │                                       Speech workers (STT/TTS, GPU or provider)
    ▼                                       Ingestion workers (parse → chunk → embed)
 Postgres + pgvector (chunks)
                                            Redis (rate limits, cache)   Tracing (Langfuse)
                                            LLM gateway → Gemini / fallback providers
```

**Today (VoxDesk):** exactly this shape, minus the queue, speech workers and LLM gateway — speech
runs inside the API process, ingestion uses FastAPI background tasks, failover lives in `llm.py`.
Each of those is a clean extraction point (see §6).

**Why this decomposition**
- **Supervisor + specialists**: the supervisor owns the conversation (memory, routing,
  confirmation); specialists are stateless and scale independently. Booking failing doesn't break
  Q&A.
- **A2A between agents**: standard task lifecycle (working / input-required / completed), streaming,
  Agent Cards for discovery — human-in-the-loop maps onto `input-required`.
- **MCP for tools**: tools behind a protocol with their own auth; the tenant is fixed by the
  connection, so the LLM can't pick another business.

---

## 4. Deep dives (pick what the interviewer cares about)

### 4.1 RAG pipeline
- **Ingestion** (async): parse PDF/MD/TXT → recursive split into **500-char chunks, 100 overlap**
  (chosen by eval: Hit@1 86% vs 82% at 1000) → embed (768-d) in batches → store with `business_id`.
- **Retrieval**: vector (HNSW, cosine) + keyword (Postgres full-text, GIN) → **RRF** (k = 60) →
  top 5. Hybrid catches exact names/prices that embeddings blur.
- **Generation**: answer only from context, cite `[n]`, refuse otherwise. **Query rewriting** in the
  router turns follow-ups into standalone queries.
- **Quality loop**: golden set → Hit@k / MRR / faithfulness (LLM judge) / refusal rate, run before
  changing chunking, models or prompts.
- **At scale**: ingestion through a queue with retries; re-embedding jobs when the embedding model
  changes (vectors from different models aren't comparable — that's why there's no embedding
  fallback); optional reranker on the top 20; per-business semantic cache for repeated FAQs.

### 4.2 Agent orchestration and booking safety
- Supervisor graph: `route → knowledge | booking | handoff | respond`; Postgres **checkpointer**
  gives per-conversation memory and the ability to pause/resume across requests.
- Booking: tool-calling loop; **write tools require confirmation** (`interrupt()` → A2A
  `input-required` → UI card or spoken "yes" → resume the same task).
- Defence in depth for side effects:
  1. Tenant from the MCP connection header — not a tool argument.
  2. Code checks customer details actually came from the customer.
  3. Customer confirmation before writes.
  4. Booking service re-validates hours and availability.
  5. **Exclusion constraint** in Postgres rejects overlapping confirmed bookings, even under races.

### 4.3 Voice latency budget
Target: first audio < 1.5 s after the customer stops speaking.

| Stage | Today (laptop CPU, push-to-talk) | At scale |
|---|---|---|
| End-of-speech detection | button release (0 ms) | VAD / endpointing ~200–300 ms |
| Speech-to-text | ~0.7 s for 5.5 s audio (Whisper base.en) | **streaming STT** → ~100–300 ms after end of speech |
| Routing | ~0.5 s | cheap model, or classify while STT finishes |
| First sentence from LLM | model-dependent | streaming, small fast model, prompt caching |
| TTS first sentence | Kokoro ~0.47× real time | streaming TTS (ElevenLabs Flash / GPU Kokoro) |

The core trick already in VoxDesk: **sentence-level pipelining** — TTS starts on sentence 1 while the
LLM writes sentence 2. Barge-in = cancel the running task when the customer speaks.

### 4.4 Multi-tenancy and security
- Every tenant row has `business_id`; every query filters by it; owner APIs use one router-level
  ownership dependency; other tenants get **404**.
- Owner auth: Argon2id passwords, JWT in an httpOnly SameSite cookie; production refuses default
  secrets.
- Customer endpoints are public (no customer accounts) → protected by per-IP and per-business rate
  limits and input guardrails before any LLM spend.
- At larger scale: Postgres row-level security as a second guard; per-tenant LLM budgets; audit log
  for bookings.

### 4.5 Observability and evaluation
- One **trace per turn** across services (trace ids propagated in A2A metadata): router decision,
  retrieved chunks, every LLM call (which provider), tool calls, latency per span.
- Product analytics per tenant (outcomes, intents, handoffs, p50/p95 time-to-first-token).
- Offline evals before every change; online: sample production traces into the judge, watch refusal
  and handoff rates for drift.

---

## 5. Data model

```
users ─< businesses ─< documents ─< chunks (vector(768) HNSW, tsvector GIN, business_id)
                    ─< services ─< bookings  (EXCLUDE overlapping confirmed per business)
                    ─< business_hours
                    ─< conversations ─< turns  (intent, outcome, latency; index business_id, created_at)
LangGraph checkpoints (thread_id = business_id:conversation_id) — full conversation state
```

Choices worth saying:
- **One Postgres** for app data, vectors and agent memory: transactions, joins, one backup. Split
  later by workload (§6), not up front.
- Bookings store `timestamptz` and the business has an IANA timezone; availability is computed in
  the business's timezone (DST-safe).
- Transcripts are not duplicated: the checkpoint is the source of truth; `turns` keeps previews.

---

## 6. Scaling to 10,000 businesses (what changes, in order)

1. **API tier**: already stateless → horizontal pods behind a load balancer; WebSockets need no
   stickiness because conversation state lives in the checkpoint store, not in memory.
2. **Connection pooling**: PgBouncer in front of Postgres (many pods × pools would exhaust
   connections).
3. **Move heavy work off the request path**: ingestion → queue + workers (retries, backpressure);
   speech → dedicated GPU workers or streaming STT/TTS providers.
4. **LLM gateway**: one place for provider routing, failover + circuit breakers (already in
   `llm.py`), per-tenant budgets and quotas, retries with jitter, response/semantic caching, and cost
   accounting.
5. **Database split by workload**:
   - checkpoints → their own database (write-heavy, prunable with a TTL);
   - analytics turns → partitioned by month, rolled up into daily aggregates;
   - chunks → partition by `business_id` hash when the table gets large; `halfvec` to halve memory;
     read replicas for retrieval.
   - A dedicated vector DB only if pgvector stops meeting latency at that size.
6. **Redis** cluster for rate limits and caches.
7. **Agents** autoscale on CPU / in-flight tasks; the A2A boundary means each can scale on its own
   curve (knowledge traffic ≫ booking traffic). Catch: VoxDesk's A2A task store is **in memory**, so a
   booking confirmation must resume on the same replica. Before running several booking replicas,
   move tasks to a **database-backed task store** (the booking graph's own state is already in the
   Postgres checkpointer). The knowledge agent is stateless and can scale out today.
8. **Multi-region** later: frontend at the edge; API + agents near the LLM provider region; data
   residency per region if required.

---

## 7. Failure handling

| Failure | Behaviour (today → at scale) |
|---|---|
| Gemini quota / outage | circuit breaker opens after 3 errors → instant failover to the fallback provider; retries only when no fallback |
| Knowledge or booking agent down | supervisor returns a friendly "can't look that up right now" and the other paths keep working; readiness endpoint reports it |
| MCP server down | booking agent replies that booking is unavailable; no partial writes |
| Redis down | rate limiter **fails open** (conversations continue), logged |
| Analytics write fails | logged and swallowed — never breaks a conversation |
| Two customers book the same slot | exclusion constraint rejects the second; agent offers other times |
| Process restart mid-confirmation | API restart: fine — the supervisor's state is in the Postgres checkpoint. Booking-agent restart: today the pending A2A task is lost (in-memory task store) and the customer must ask again → at scale, a database-backed A2A task store |
| Prompt injection | guardrails block known patterns; tenant and confirmation are enforced in code, so a successful injection still can't cross tenants or book silently |
| Bad deploy / quality regression | eval suite before release; traces + outcome rates to detect drift; roll back images |

---

## 8. Trade-offs to volunteer

- **Multi-agent vs single agent**: isolation and independent scaling vs extra hops and operational
  complexity. For one small business a single agent is enough; for a platform the split pays off.
- **pgvector vs dedicated vector DB**: simplicity and transactional consistency vs specialised
  performance at very large scale.
- **Local speech vs cloud speech**: cost/privacy/control vs latency and quality at scale (VoxDesk
  supports both behind one interface).
- **Fixed-window rate limiting**: simple and cheap; allows bursts at window edges (sliding window or
  token bucket if that matters).
- **Confirmation for writes only**: safety vs friction.
- **Push-to-talk vs full-duplex**: simpler and robust today; full-duplex needs VAD, echo
  cancellation and streaming STT.

---

## 9. Whiteboard script (45-minute round)

| Minute | Do | Say |
|---|---|---|
| 0–5 | Requirements list + non-functional table | "Voice latency and booking correctness are the two hard constraints." |
| 5–10 | Estimates | "LLM calls are the bottleneck and the cost; our servers aren't." |
| 10–20 | High-level diagram (§3) | Name each protocol on its arrow: SSE, WebSocket, A2A, MCP. |
| 20–35 | Two deep dives — let them choose; default **booking safety** + **voice latency** | Defence-in-depth list; latency budget table. |
| 35–40 | Scaling steps (§6) | In order, with the reason for each. |
| 40–45 | Failures + trade-offs | "What I built today vs what I'd add at 10k tenants." |

**Close with:** *"I've built the core of this as VoxDesk — supervisor and specialist agents over A2A,
an MCP booking server, hybrid RAG with evals, a streaming voice pipeline, failover, tracing and
multi-tenancy — so the parts I'd add at scale are the queue, speech workers, LLM gateway and database
split."*
