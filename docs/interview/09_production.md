# 09 — Production Readiness: Resilience, Security, Observability, Docker

> Phase 5 (Steps 1–4) plus the resilience work done during Phase 4. This is what separates
> "a demo that works on my laptop" from "a system you could run for real customers".

---

## 1. Plain English first

| Concern | Question an interviewer asks | VoxDesk's answer |
|---|---|---|
| Resilience | "What if your LLM provider goes down or rate-limits you?" | Automatic fallback to a second provider + circuit breaker |
| Health | "How do you know the system is up?" | Liveness vs readiness endpoints, checked in parallel |
| Deployment | "How do you ship it?" | One Docker image for all backend services, Compose profiles, CI builds images |
| Security | "How do you handle auth and multiple customers?" | Argon2id + JWT in httpOnly cookie; tenant isolation returning 404 |
| Abuse | "What stops someone burning your LLM budget?" | Redis rate limits per IP / business / user |
| Safety | "What about prompt injection?" | Input guardrails before any LLM call (+ defence in depth from earlier phases) |
| Observability | "How do you debug a multi-agent system?" | Langfuse traces: one trace per turn across processes |
| Quality | "How do you know it actually works?" | Evaluation suite — see `10_evaluation.md` |

---

## 2. LLM fallback + circuit breaker

**Files:** `app/llm.py`, `app/circuit_breaker.py`

### The problem (real, not hypothetical)
Gemini's free tier gave this project **20 requests/day per model**. A single booking conversation
makes several LLM calls, so the quota ran out during testing and customers saw errors.

### Fallback
Every chat model is `Gemini.with_fallbacks([backup])`. The backup is **any OpenAI-compatible
provider** chosen by config (`FALLBACK_BASE_URL`, `FALLBACK_MODEL`, `FALLBACK_API_KEY`).

How the backup was chosen — **by measurement, not guesswork**:
1. Hugging Face: token valid but account had **no credits (402)**.
2. Groq: `llama-3.3-70b-versatile` had been **retired (404)** → listed the models the key could access.
3. Live-tested candidates on the three things VoxDesk needs:
   `openai/gpt-oss-120b` → plain answer **247 ms**, tool call **297 ms**, structured output **596 ms** ✅;
   `qwen/qwen3.8-27b` → free tier capped at 1k output tokens/min ❌.

Two subtle details:
- `with_fallbacks` only forwards `bind_tools()` / `with_structured_output()` to the backup if those
  methods are **annotated as returning a `Runnable`** — verified for Gemini, fixed in our own override.
- OpenAI-compatible providers often don't support strict JSON-schema output, so the backup uses
  **function calling** for structured output (the router).
- **Embeddings deliberately have no fallback**: a different embedding model produces vectors in a
  different space; they can't be compared with stored ones without re-embedding everything.

### No retries when a backup exists
Measured: a Gemini 429 fails in **0.49 s with 0 retries vs 2.34 s with 2**. With a backup configured,
Gemini isn't retried — it fails over immediately.

### Circuit breaker
Even 0.5 s per call adds up when Gemini is known to be out of quota.
```
CLOSED ──3 outage errors in a row──► OPEN (Gemini skipped in ~0 ms for 5 min)
   ▲                                     │
   └── success ◄── HALF-OPEN (one trial call) ── failure → OPEN again
```
- Counts only **outage errors** (429, 5xx, timeouts) — a 400 is our bug, not an outage.
- Implemented as a mixin on the chat model class, so the plain model, the tool-bound model and the
  structured-output model all share one breaker (they share one quota).
- **Bug found by tests:** LangChain's default async path calls the sync path in a thread; both were
  guarded, so one failure counted twice. Fixed with a context flag ("only the outermost call counts").
- `LLM_PRIMARY=fallback` flips the order manually (handy while a quota is exhausted).

> "I treat LLM providers as unreliable dependencies: primary with automatic failover to a second
> provider, a circuit breaker so we stop paying for calls to a provider we know is down, and no
> retries when a backup exists — I measured the latency each change saved."

---

## 3. Health checks: liveness vs readiness

- `GET /health` — **liveness**: is the process alive? No dependencies checked.
- `GET /health/services` — **readiness**: DB, MCP server, both A2A agents — **in parallel**, **2 s
  timeout each**, so one dead dependency can't hang the endpoint. Agents' public Agent Cards double
  as health probes. Dashboard shows "All systems operational" / per-service hover panel.

> "Kubernetes restarts a container that fails liveness but only stops routing to one that fails
> readiness — a dead booking agent shouldn't get the API restarted."

---

## 4. Docker

**Files:** `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`

- **One backend image** runs as `api`, `mcp`, `knowledge`, `booking` (same code, different command) —
  consistent, built once. uv-locked deps, dependency layer cached, **non-root user**.
- **Frontend**: multi-stage build with Next.js `standalone` output → 243 MB image.
- **Compose profiles**: `docker compose up -d` = Postgres + Redis only (dev mode);
  `docker compose --profile app up -d --build` = all 7 services.
- **Healthchecks gate start-up order** (e.g. booking agent waits for MCP to be healthy).
- API container runs **migrations on start** and downloads voice models into a **volume** (not baked
  into the image).
- **CI builds both images** on every push → broken Dockerfiles are caught before deployment day.
- Image sizes: backend 1.6 GB (speech runtimes: ONNX Runtime, CTranslate2, PyAV); a separate voice
  service would slim the others — a known trade-off.

---

## 5. Authentication & multi-tenancy

**Files:** `app/auth.py`, `app/api/auth.py`, `app/api/businesses.py`

| Decision | Why |
|---|---|
| **Argon2id** password hashing (pwdlib) | Memory-hard → expensive to brute-force leaked hashes on GPUs; current OWASP recommendation |
| **JWT (HS256, 7 days) in an httpOnly cookie** | JavaScript can't read it → an XSS bug can't steal the session |
| **SameSite=Lax** | Cross-site POSTs don't carry the cookie → CSRF protection |
| Also accepts `Authorization: Bearer` | Swagger and API clients |
| Same error + same timing for unknown email vs wrong password (dummy hash check) | No user enumeration |
| Ownership check as a **router-level dependency** | Every current and future route under `/businesses/{id}/…` is protected by default — this also closed 3 endpoints that had no check |
| Other tenants' businesses → **404, not 403** | Don't reveal which ids exist |
| API refuses to start in production with the dev JWT secret or insecure cookies | Misconfiguration fails loudly |

**Customers never log in.** Each business gets a public **slug** page `/c/<slug>`; chat and voice
endpoints stay public (they only need the business id). Management requires the owner.

**Migrating existing data:** adding `slug NOT NULL` to a table with rows needs a **3-step migration**
(add nullable → backfill → enforce). Businesses created before accounts existed are claimed by the
**first signup**.

> "Tenant isolation is enforced in one place — a FastAPI dependency on the router — so it can't be
> forgotten on a new endpoint, and it returns 404 so other tenants can't probe ids."

---

## 6. Rate limiting

**File:** `app/ratelimit.py`

- **Fixed-window counters in Redis** (`INCR` + `EXPIRE NX` in one transaction). Atomic and **shared
  across replicas** (an in-process counter would multiply the limit by the number of instances).
- Limits: chat/resume/voice **20/min per IP + 120/min per business** (protects each tenant's LLM
  budget); login/signup **10/min per IP** (slows password guessing); uploads **20/min per user**.
- Over the limit → **429 + `Retry-After`**; in voice the agent says "please slow down".
- **Fails open**: if Redis is down, requests are allowed and logged — availability over strictness
  for a customer-facing assistant. (A payments API might choose fail-closed.)
- Fixed window vs sliding window / token bucket: fixed is simplest and good enough here; it allows
  bursts at window edges — a sliding window or token bucket smooths that.

---

## 7. Input guardrails

**File:** `app/guardrails.py`

Before any graph or LLM work (chat and voice transcripts):
- **Length limit** (2,000 chars) — huge inputs are a cost/latency attack.
- **Prompt-injection patterns**: "ignore previous instructions", "reveal your system prompt",
  `system:` role lines, chat-template tokens, "developer mode", "you are now…".

A blocked message gets a polite redirect ("I can only help with questions about Glow Studio…") and
**costs nothing** — no checkpoint read, no LLM call. The Inspector shows a "Guardrail" section.

**Tested in both directions:** 8 attacks caught, 5 legitimate messages allowed. Two **false positives**
were found and fixed ("forget my previous booking rules", "show me the original message I sent") —
blocking real customers is a bug too.

**This is one layer, not the whole defence** (defence in depth from earlier phases):
tenant id comes from the MCP connection, not the LLM · writes need human confirmation · tool
arguments are validated and grounded · the DB enforces invariants. Upgrade path: an ML classifier
(e.g. Llama Prompt Guard) behind the same `check_message` interface.

> "Regex guardrails are cheap and catch the obvious attacks, but I don't rely on them: the system is
> designed so that even a fully hijacked LLM can't cross tenants or change data without the
> customer's confirmation."

---

## 8. Observability with Langfuse

**File:** `app/tracing.py`

- **One trace per turn** (chat or voice): session = conversation, user = business, tags = channel.
- The **LangChain callback handler** captures the router decision, every LLM call (with **model name —
  Gemini or the fallback**, tokens, latency) and every MCP tool call with inputs/outputs.
- **Distributed tracing over A2A:** the supervisor puts its trace id + current span id in the A2A
  message metadata; each agent calls `trace_turn(..., parent=metadata)` and **continues the same
  trace** from another process. One customer turn = one timeline across API, knowledge agent,
  booking agent and MCP tools.
- Voice adds **speech-to-text** and per-sentence **text-to-speech** spans — exactly where time goes.
- Inspector and Voice page link to the trace ("Open trace in Langfuse").
- **No-op without keys**; traces flushed on shutdown. Langfuse **Cloud** chosen: self-hosting needs
  ClickHouse + MinIO + more, too heavy for the dev laptop (~5 GB RAM free).

> "In a multi-agent system the hardest bugs cross process boundaries, so I propagate the trace
> context over A2A — the agents' LLM and tool calls appear inside the supervisor's trace."

---

## 9. Testing (113 tests at the end of Step 4)
| File | Proves |
|---|---|
| `test_llm_fallback.py` | Backup answers on 429; tool binding reaches the backup; key accepted under common names |
| `test_circuit_breaker.py` | State machine with a fake clock; half-open behaviour; 400s ignored; open circuit skips the provider entirely; streaming falls back; `LLM_PRIMARY` order |
| `test_health.py` | Readiness reports each dependency |
| `test_auth.py` | httpOnly cookie, duplicates/weak passwords, identical errors, Bearer, expired/forged tokens, **owner B can't see/touch owner A's data (404)**, first-signup claim, public page fields, production safety |
| `test_protection.py` | Limiter windows, independence, fail-open, **real Redis** atomicity; login brute force → 429; chat limited before any work; every attack/legit guardrail case; blocked message never reaches agents |
| `test_tracing.py` | No-op without keys; parent-context mapping; supervisor sends trace ids to agents |

---

## Q&A

**Q: Your LLM provider is down. What happens?**
A: Calls fail over to a second, OpenAI-compatible provider immediately (no retries when a backup
exists); after three outage errors a circuit breaker skips the primary for five minutes, then tries
one call to see if it's back.

**Q: Why store the JWT in a cookie instead of localStorage?**
A: An httpOnly cookie can't be read by JavaScript, so XSS can't exfiltrate it; SameSite=Lax blocks
cross-site POSTs. localStorage is readable by any script on the page.

**Q: How do you enforce tenant isolation?**
A: A router-level FastAPI dependency checks that the signed-in user owns the business in the path;
other tenants get 404. For the agents, the tenant travels in the MCP connection header, never in an
LLM-controlled argument.

**Q: Why fail open on rate limiting?**
A: For a customer-facing assistant, refusing everyone because Redis blipped is worse than briefly
allowing extra requests. A payment or auth-critical path might fail closed.

**Q: How do you defend against prompt injection?**
A: Cheap input guardrails first, but mainly architecture: the model can't choose the tenant, can't
write without human confirmation, tool inputs are validated and grounded, and the database enforces
invariants.

**Q: How do you debug a request that went through three services?**
A: Langfuse distributed tracing — the trace id is propagated in A2A metadata, so the supervisor,
agents, LLM calls and MCP tool calls appear as one timeline, with the model used and latency per step.

**Q: Liveness vs readiness?**
A: Liveness: is the process alive (restart if not). Readiness: can it serve traffic right now —
dependencies reachable (stop routing to it if not).
