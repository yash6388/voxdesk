# VoxDesk — Progress Log

> Update at the end of every work session: tick tasks, set "Next up", add decisions.

## Current status
**Phase 5 — Production polish: steps 1–7 ✅** · next: owner testing (step 8) → fixes

### Phase 4 done
- [x] Voice stack decided (option C): local faster-whisper + Kokoro by default, ElevenLabs via `STT_PROVIDER` / `TTS_PROVIDER` — no PyTorch (CTranslate2 + ONNX Runtime, int8)
- [x] `scripts/download_voice_models.py` (Kokoro int8 ~92 MB + voices, Whisper base.en); models in gitignored `backend/data/models`
- [x] `app/voice/`: `audio.py` (PyAV decode → 16 kHz mono; WAV encode), `text.py` (incremental sentence splitter, speakable text incl. ₹ → rupees, spoken yes/no), `providers.py` (Whisper/Kokoro/ElevenLabs behind STT/TTS protocols, background warm-up)
- [x] `app/conversation.py`: transport-independent turn runner shared by chat (SSE) and voice (WebSocket)
- [x] `/voice/{business_id}` WebSocket: STT → supervisor → per-sentence TTS pipeline; spoken + clicked confirmation; barge-in via task cancellation; timings (stt, first token, first audio, total)
- [x] Frontend Voice page: hold-to-talk button (animated), live transcript, confirm card (or say yes/no), engines + latency panel, type-instead fallback; sidebar Voice enabled; landing copy updated
- [x] 65 tests (17 new): text helpers, PyAV decode, ElevenLabs request shapes (MockTransport), WebSocket end-to-end incl. spoken booking confirmation
- [x] Live: real Whisper transcribed speech sent over the WebSocket; real Kokoro spoke the reply (Gemini still 429)
- [x] **LLM fallback:** every chat model is `Gemini.with_fallbacks([OpenAI-compatible model])` when `FALLBACK_API_KEY` (or `HF_TOKEN`/`HUGGINGFACE_API_KEY`) is set — provider chosen by `FALLBACK_BASE_URL` + `FALLBACK_MODEL` (Groq / OpenRouter / Hugging Face) (router, small talk, knowledge agent, booking agent tool calls); structured output forced to function-calling for HF providers; embeddings deliberately have no fallback. 5 tests (70 total). Live: Hugging Face token valid but account has **no inference credits (402)** → switch provider (e.g. Groq free tier) or buy credits
- [x] **Full end-to-end verified live** (all services + Groq fallback): small talk; knowledge via A2A with follow-up rewrite; booking via A2A → MCP list/check/book → input-required → confirm → saved in Postgres; voice question → Whisper → knowledge agent → Kokoro
- [x] Latency fix: with a fallback configured, Gemini `max_retries=0` (a 429 now fails over in ~0.5 s instead of ~2.3 s per call)
- [x] **Circuit breaker** on Gemini (`app/circuit_breaker.py`): 3 outage errors (429/5xx/timeout, not 400s) in a row → OPEN for 300 s (calls fail in ~0 ms → fallback) → HALF-OPEN trial → CLOSED on success; shared across plain/tool-bound/structured wrappers; guards sync/async/stream paths; double-count bug found by tests and fixed with a context flag
- [x] `LLM_PRIMARY=fallback` makes the fallback (Groq) primary and Gemini the backup
- [x] Booking tools return a short customer `reference` (e.g. `DC2A71`); prompt forbids reading out ids
- Measured on laptop CPU: Whisper ~0.7 s for a 5.5 s utterance; Kokoro ~2.6 s for 5.5 s of audio (RTF ~0.47)

### Phase 3 done
- [x] `a2a-sdk` 1.2 (v1, protobuf types); prototyped streaming + input-required + resume first (found the "first artifact chunk must not append" rule)
- [x] `app/a2a/server.py` (Agent Card builder, app factory with bearer auth, `TextStream`, `emit_data`) and `app/a2a/client.py` (`A2AAgent`: card discovery, streaming → simple events)
- [x] **Knowledge agent** (`app/agents/knowledge.py`, :8101): hybrid RAG, streamed answer artifact + sources artifact
- [x] **Booking agent** (`app/agents/booking.py`, :8102): booking graph moved in (`graph/booking_graph.py`), own Postgres memory, graph interrupt → A2A `input-required`, resume on same task
- [x] **Supervisor** (`graph/supervisor.py`): route → delegate (knowledge/booking) or local small talk; relays agent stream via LangGraph custom stream; `booking_confirm` interrupt ↔ A2A input-required; fallbacks when agents fail
- [x] Shared modules: `llm.py`, `security.py` (BearerKeyMiddleware, also used by MCP), `errors.py`, `graph/common.py`, `graph/checkpoint.py`; `builder.py` removed
- [x] Chat API: `custom` stream mode, new `delegation` SSE event; UI/API contract otherwise unchanged
- [x] Frontend: Agent Inspector shows the handling A2A agent, task id and state
- [x] `scripts/dev_services.sh` runs MCP + both agents with labelled logs
- [x] `GET /health/services` readiness check (DB, MCP, both agents in parallel, 2 s timeout each; MCP got a public `/health`); sidebar shows overall status + per-service hover panel
- [x] 47 tests: real A2A protocol in-process (card, 401, streaming, input-required → resume), supervisor delegation/HITL/fallbacks, booking graph
- [x] Live: Agent Cards served publicly, JSON-RPC without key → 401; full Gemini conversation blocked by free-tier 429 (graceful message shown end to end)

### Phase 2 done
- [x] Models + migration: `services`, `business_hours`, `bookings` (+ `businesses.timezone/currency`); **exclusion constraint** (btree_gist) prevents overlapping confirmed bookings
- [x] `app/booking/service.py`: availability (30-min steps, hours, past, 60-day horizon), create/find/cancel/reschedule, phone normalisation; shared by MCP + REST
- [x] **MCP server** `app/mcp/server.py` (FastMCP, Streamable HTTP :8001, stateless): 7 tools; bearer-key middleware; tenant from `X-Business-Id` header (no `business_id` in tool schemas)
- [x] **Booking agent** in LangGraph: `booking_agent ⇄ tools` via `langchain-mcp-adapters`; write tools → `confirm` node with `interrupt()` → `/chat/resume`
- [x] Guardrails: ids validated + **customer name/phone grounded in customer messages** before confirmation; booking agent sees last 3 full turns; graceful reply if MCP is down
- [x] Rate-limit handling: LLM `max_retries=2`, friendly 429 message
- [x] Owner REST: services (create, activate/deactivate), hours (replace week), bookings (list, owner cancel)
- [x] Frontend: Services & hours page, Bookings page (auto-refresh, business timezone), confirmation card in chat (survives reload), Inspector shows MCP tool calls; sidebar updated; landing copy updated (no jargon)
- [x] `scripts/seed_demo.py` (idempotent demo data)
- [x] 39 backend tests (23 new): booking rules incl. forced concurrency race, MCP tools + auth, HITL approve/decline, guardrail, MCP-down
- [x] Verified live: list_services → check_availability → asks name/phone → confirm card → resume → booked (shows on Bookings page)

### Phase 1 backend done
- [x] Models (businesses, documents, chunks) + Alembic migration (pgvector extension, HNSW + GIN indexes)
- [x] Ingestion: upload (PDF/TXT/MD) → background task → parse → chunk → Gemini embeddings (768-d) → pgvector
- [x] Hybrid retrieval: pgvector cosine + Postgres full-text, fused with RRF in one SQL query; `/search` debug endpoint
- [x] LangGraph graph: route (intent + standalone query rewrite) → retrieve → respond; booking placeholder branch
- [x] Postgres checkpointer (AsyncPostgresSaver + psycopg pool) → multi-turn memory; `/chat` SSE streaming; history endpoint
- [x] 13 tests (fake embedder + fake LLMs, real Postgres test DB); CI runs pgvector service
- [x] Verified live with Gemini on `samples/glow-studio-salon.md` (follow-up rewrite, refusal on unknown info, routing)

### Phase 1 frontend done
- [x] Home: list + create businesses
- [x] Workspace `/b/[id]`: document upload (multi-file), status polling while processing, delete
- [x] Streaming chat: typed SSE parser over `fetch` (POST), route badge + searched query, collapsible sources, error display
- [x] Conversation restore after reload (thread id in localStorage → history from checkpoint), "New chat"
- [x] Lint + typecheck + build pass; verified live: events `meta → route → sources → token… → done`
- [x] **SaaS redesign:** landing page; `/dashboard` app shell with sidebar (mobile drawer); businesses cards + create modal + empty state; knowledge base page (stats, drag-and-drop, status table); Playground with citation chips, suggestions, typing dots and **Agent Inspector** (route, rewritten query, sources, time-to-first-token); design system in `components/ui/` (brand gradient, light/dark tokens, Lucide icons)

## Next up — Phase 5 (production polish) — agreed plan (2026-10-18)
Order: 1 → 6, then final docs; deployment target decided later (repo made deploy-ready).
- [x] 1. Docker: one backend image (API/MCP/agents, non-root, uv-locked deps) + standalone Next.js image; Compose `app` profile (`docker compose --profile app up -d --build` → 7 services with healthchecks, voice models in volumes, migrations on API start); CI job builds both images. Smoke-tested images: API readiness all up, MCP 401 without key, frontend 200. Images: backend 1.6 GB (speech runtimes), frontend 243 MB
- [x] 2. Auth + multi-tenancy: `users` table; Argon2id hashing (pwdlib); JWT (HS256, 7 days) in an **httpOnly SameSite=Lax cookie** + Bearer header for API clients; `/auth/signup|login|logout|me`; constant-time-ish login (dummy hash) + identical errors; businesses get `owner_id` + unique `slug` (3-step migration with backfill); documents/booking routers owner-only via router-level dependency (closed 3 unchecked endpoints); other tenants get **404 not 403**; first signup claims pre-auth businesses; `/public/businesses/{slug}`; production refuses dev JWT secret / insecure cookies. Frontend: login/signup split-screen pages, `AuthProvider` + `RequireAuth`, sidebar account + sign out, landing Log in / Get started, **public customer page `/c/<slug>`**, "Copy customer link" in Playground. 88 tests (11 new auth/isolation)
- [x] 3. Protection: **Redis fixed-window rate limiter** (`app/ratelimit.py`; INCR + EXPIRE NX in a transaction; fails open if Redis is down) — chat/resume/voice 20/min per IP + 120/min per business, login/signup 10/min per IP, uploads 20/min per user; 429 + `Retry-After`. **Input guardrails** (`app/guardrails.py`): 2,000-char limit + prompt-injection patterns, checked before any graph/LLM work (chat + voice); 2 false positives found and fixed; voice audio capped at 5 MB. Inspector shows "Guardrail" when it fires. CI now has a Redis service. 110 tests (22 new)
- [x] 4. Observability: **Langfuse** (`app/tracing.py`, SDK v5/OpenTelemetry; cloud or self-hosted; no-op without keys). One trace per chat/voice turn (session = conversation, user = business, tags = channel) via the LangChain callback handler → router, LLM calls (model name = Gemini vs fallback), tokens, MCP tool calls. **Distributed tracing over A2A**: supervisor sends trace/parent-span ids in message metadata; agents continue the same trace (knowledge: retriever span + LLM; booking: graph + tools). Voice adds speech-to-text and per-sentence text-to-speech spans. Inspector + Voice page show "Open trace in Langfuse"; traces flushed on shutdown. 113 tests. Live check pending Langfuse keys. (Self-host ruled out: ~5 GB free RAM vs ClickHouse needs)
- [x] 5. **Evaluation suite** (`backend/evals/`, `uv run python -m evals.run`): golden set (22 retrieval, 13 routing, 10 answer, 5 booking) over 4 sample docs; temporary business created/deleted per run; production `classify()`/`answer_messages()` reused. Results: hybrid@500 **Hit@1 86% · Hit@3 100% · MRR 0.93** (beats vector 82%, keyword 77%; 1000-char 82%/0.90 at equal overlap) · routing **100%** · fact accuracy **100%** · faithfulness **5.0/5** (LLM judge, Groq gpt-oss-120b) · correct refusals **100%** · booking task success **100%**. **Production chunk size 1000 → 500 (overlap 150 → 100)**. Caught: full-width 【n】 citations from the fallback model (fixed in TTS + UI + prompt), evaluator whitespace bug, rate-limit errors scored as failures (now retried/excluded), mislabelled golden case, confounded first chunk-size comparison. Latency in evals inflated by Groq free-tier TPM cap (single call ~270 ms). Reranker experiment → future. Report committed: `backend/evals/reports/latest.md`. Interview notes `10_evaluation.md` + `QA_BANK.md` (100 Q&A)
- [x] 5b. **Share page** (`/dashboard/b/<id>/share`): customer link, **QR code** (H error correction, PNG download), **website chat bubble** (`public/widget.js`: dependency-free, lazy iframe, mobile full-screen, Escape/close via origin-checked postMessage, live preview on the page), **inline iframe embed**; `/c/<slug>?embed=1` compact mode; **anti-clickjacking headers** (`X-Frame-Options: DENY` + `frame-ancestors 'none'` everywhere except `/c/*`); `samples/demo-website.html` = pretend salon site for cross-origin demo
- [x] 6. **Analytics + human handoff.** New tables `conversations` (one per thread; status open / needs_human / resolved, handoff reason, turn count) and `turns` (intent, outcome, user/reply text, first-token + total ms). `app/analytics.py` `TurnRecorder` watches the **same event stream the client gets** and derives one outcome per turn (guardrail > error > handoff > booked > booking_declined > booking_pending > answered); saved with one atomic Postgres **upsert** (`INSERT … ON CONFLICT DO UPDATE`); failures logged, never break a conversation. Wired into chat, resume and voice. **Handoff intent** in the supervisor: router → `handoff` node → reply + `handoff` event → conversation flagged `needs_human`. Owner API (`app/api/insights.py`): `/analytics?days=` (counts by outcome/intent/channel, daily series **in the business timezone**, p50/p95 time-to-first-token via Postgres `percentile_cont`), `/conversations?status=`, transcript from the LangGraph checkpoint, `/resolve`. Frontend: **Analytics page** (6 KPI tiles, messages-per-day area chart with crosshair tooltip + table view, outcome/intent/channel bars; hand-written SVG, chart colours checked with a palette validator for light + dark) and **Inbox** (needs-a-human list, transcript, Mark resolved; sidebar badge). Inspector shows Handoff. 3 handoff routing cases added to the golden set → routing **16/16**. Found in testing: timezone bug in the daily range (fixed); **live bug: after a handoff the customer's "it's Priya, 98765…" was routed to handoff again and got the same canned reply** → guard in the route node (code, not prompt — the router kept saying handoff); relayed events leaked an internal `type` key; a single-suite eval run overwrote the full `latest.md` (now only full runs replace it); **the golden set had never been committed** — `.gitignore`'s `data/` rule (meant for voice models) also matched `backend/evals/data/` → exception added. 130 tests (7 new)
- [x] 7. Final docs in `docs/interview/`: **`PROJECT_EXPLAINED.md`** (end-to-end: request flows, components, numbers, trade-offs, bugs, limitations), **`PITCH.md`** (30 s / 2 min / 5 min versions, whiteboard, demo script, follow-up steering, resume bullets), **`SYSTEM_DESIGN.md`** (requirements, estimates for 10k businesses, HLD, deep dives, scaling steps, failure table, 45-min script). README rewritten as a product README (features, quick start, configuration, widget, testing; no internals). Writing them surfaced a real limitation: A2A tasks use an in-memory store → booking-agent restart loses a pending confirmation and blocks multi-replica booking agents (documented; DB-backed task store = next step). Demo GIF/screenshots → after owner testing, with real data
- [ ] 8. Owner's personal testing (1–2 days) → fix UI/bugs found
- [x] Next.js 15.5.4 → 15.5.28 (patch; clears the critical advisory). Remaining 2 high (postcss/sharp bundled in Next) need Next 16 — breaking, later
- [x] Owner walkthrough (2026-10-20): chat Q&A, booking with confirmation, voice booking, customer Share link booking, handoff, analytics — all worked; no overlapping bookings
- [ ] Later: choose deployment target and deploy
- Pending live checks: latency after no-retry/breaker changes; ElevenLabs; full voice booking

## Before Phase 4 (agreed checkpoint)
- Review Phases 1–3 together: what was built and why.
- Decide voice stack (local models vs cloud STT/TTS APIs) **before** installing anything heavy.
  `/home` had only ~4.6 GB free on 2026-10-17; cleaned caches on 2026-10-18 → ~27 GB free (no longer a blocker).
  Options: cloud APIs (no PyTorch), or run local models inside Docker (root partition has ~55 GB).

## Phase checklist
- [x] Phase 0 — Setup
- [x] Phase 1 — Text core + RAG
- [x] Phase 2 — MCP
- [x] Phase 3 — A2A
- [x] Phase 4 — Voice
- [ ] Phase 5 — Production polish

## Decision log
| Date | Decision | Reason |
|---|---|---|
| 2026-10-17 | Project = VoxDesk (voice AI agent platform for businesses) | Covers agentic/MCP/A2A/RAG/voice; real B2B use case; complements FilingLens |
| 2026-10-17 | Single monorepo `voxdesk` | One resume link, one README, one `docker compose up` |
| 2026-10-17 | Twilio dropped for now | Not needed for core demo; voice pipeline kept transport-agnostic so it can be added later |
| 2026-10-17 | pgvector over Qdrant | Postgres already needed for bookings + checkpoints; SQL tenant filtering; breadth beyond FilingLens |
| 2026-10-17 | Build own MCP server + consume via adapters | Demonstrates both sides of MCP |
| 2026-10-17 | Python 3.13 (not 3.12) | Already installed locally; 3.12 download stalled; all planned libs support 3.13 |
| 2026-10-17 | Docker host ports 5433/6380 | Local Postgres/Redis already occupy 5432/6379 |
| 2026-10-17 | Gemini `gemini-embedding-001` at 768 dims | No local model/GPU; 768 keeps index small and fast; `task_type` differs for docs vs queries |
| 2026-10-17 | Router on `gemini-2.5-flash-lite`, answers on `gemini-2.5-flash`, thinking off | Cheap/fast classification; thinking adds latency that hurts voice later |
| 2026-10-17 | Router also rewrites follow-ups into standalone search queries | One LLM call does intent + query rewrite; fixes "and how long does it take?" retrieval |
| 2026-10-17 | Thread IDs namespaced as `{business_id}:{thread_id}` | Prevents cross-tenant access to conversation checkpoints |
| 2026-10-17 | FastAPI BackgroundTasks for ingestion (not Celery yet) | Simple for now; move to a queue if uploads get large/many |
| 2026-10-17 | Frontend parses SSE manually with fetch + ReadableStream | EventSource is GET-only; chat needs POST with JSON body |
| 2026-10-17 | Thread id in localStorage, history from server checkpoint | Server is source of truth; browser only remembers which thread |
| 2026-10-17 | Poll document status (2s, only while processing) | Simple and sufficient; push (Redis pub/sub) only if needed later |
| 2026-10-17 | SaaS-style UI: landing + dashboard shell, shared `components/ui` design system | Owner wants a modern, attractive product look, not a dev tool; consistent components keep new pages cheap |
| 2026-10-17 | Gradient only for brand moments; solid indigo + shared `BRAND_TINT` elsewhere | Gradient everywhere looked busy/generic; restraint reads as more premium |
| 2026-10-17 | Agent Inspector panel with client-measured TTFT | Makes routing/retrieval visible for demos/debugging; TTFT is the key metric for voice later |
| 2026-10-17 | MCP server lives in `backend/app/mcp` (separate process), not `mcp_servers/` | Shares DB models + booking rules with the API; still deployed/run independently on :8001 |
| 2026-10-17 | Postgres exclusion constraint for bookings (btree_gist) | App checks can't stop concurrent double booking; DB guarantees it |
| 2026-10-17 | Tenant via `X-Business-Id` header on MCP connection; bearer key auth | LLM can't choose/inject another tenant; tool schemas have no business_id |
| 2026-10-17 | Stateless Streamable HTTP for MCP | Horizontal scaling; no sticky sessions |
| 2026-10-17 | HITL `interrupt()` only for write tools | Safety for real actions without confirming every lookup |
| 2026-10-17 | Code guardrail: name/phone must appear in customer messages | Gemini invented "John Doe" despite prompt rules (found in live test) |
| 2026-10-17 | Booking agent context = last 3 full turns (with tool messages) | Dropping tool results made the agent invent service ids (found in live test) |
| 2026-10-17 | Separate `date` and `time` tool args | LLMs fill these more reliably than tz-aware ISO datetimes |
| 2026-10-17 | `max_retries=2` + friendly 429 message | SDK backoff made users wait ~35 s before a generic error |
| 2026-10-18 | Agents live in `backend/app/agents` (separate processes, shared package) | Reuse RAG/booking code + models; still independently runnable on :8101/:8102 |
| 2026-10-18 | Prototype the A2A SDK before building | v1 SDK differs from tutorials; found artifact-append rule + metadata-not-persisted |
| 2026-10-18 | Supervisor keeps conversation, routing, small talk, confirmation UI | Agents stay focused; small talk avoids a network hop; UI contract unchanged |
| 2026-10-18 | Knowledge agent receives the router's standalone query | Agent can be stateless |
| 2026-10-18 | HITL = booking agent `input-required` + supervisor `interrupt()`, reply on same task | Native A2A lifecycle; survives across HTTP requests on both sides |
| 2026-10-18 | Relay agent output via LangGraph custom stream | Remote tokens/sources/tool calls reach the browser in real time |
| 2026-10-18 | Agent Card public; JSON-RPC bearer-protected (A2A_API_KEY) | Discovery is public by design; invocation needs credentials |
| 2026-10-18 | Separate liveness (`/health`) and readiness (`/health/services`) | Orchestrators restart on liveness, route traffic on readiness; one dead dependency shouldn't restart the API |
| 2026-10-18 | Voice option C: local faster-whisper + Kokoro default, ElevenLabs switchable | Free/private/no quotas in dev; premium voice for demos; same interface |
| 2026-10-18 | Kokoro int8 ONNX (~92 MB) over full model (310 MB) | Smaller + faster on CPU, near-identical quality |
| 2026-10-18 | Decode audio with PyAV ourselves | faster-whisper 1.2.1 passes an argument PyAV 19 removed; PyAV 14 has no wheel |
| 2026-10-18 | WebSocket for voice; shared `conversation.run_events` for chat + voice | Bidirectional audio + control; one source of truth for turn logic |
| 2026-10-18 | Per-sentence TTS pipelined with LLM streaming; warm-up at startup | Minimises time to first audio |
| 2026-10-18 | Spoken confirmation: any "no" wins, ambiguity re-prompts | A wrong "yes" books a real appointment |
| 2026-10-18 | LLM fallback to any OpenAI-compatible provider (default Hugging Face router; Groq/OpenRouter by config) | Free-tier Gemini 429s; provider redundancy is a standard resilience pattern |
| 2026-10-18 | Fallback model = Groq `openai/gpt-oss-120b` | Free tier, ~250–600 ms incl. tool calls + structured output; chosen by live comparison against the account's model list |
| 2026-10-18 | No Gemini retries when a fallback exists | Measured 0.49 s vs 2.34 s to fail on 429; retries were adding ~2 s per call per layer |
| 2026-10-18 | Short booking `reference` alongside `booking_id` | Agent still needs the full id for follow-up tools; customers (and voice) need something short |
| 2026-10-18 | Circuit breaker on the primary LLM + `LLM_PRIMARY` switch | Stop paying a 429 round trip per call when the provider is known to be down; manual override for dev |
| 2026-10-18 | One backend image for API, MCP and agents; Compose profiles | Same code, different command; `docker compose up` keeps the infra-only dev flow, `--profile app` runs everything |
| 2026-10-18 | Voice models in Docker volumes, not baked into images | Smaller images; downloaded once on first start |
| 2026-10-18 | JWT in httpOnly cookie (+ Bearer for API clients) | JS can't read it → XSS can't steal sessions; SameSite=Lax blocks cross-site POSTs (CSRF) |
| 2026-10-18 | Argon2id via pwdlib | Memory-hard; current OWASP recommendation |
| 2026-10-18 | Other tenants' resources → 404, not 403 | Don't reveal which ids exist |
| 2026-10-18 | Analytics recorded from the event stream, not inside the graph | One recorder for chat + voice; the graph and agents stay unaware of analytics |
| 2026-10-18 | Turn analytics in Postgres tables (not Langfuse) | Owner-facing product data must be queryable per tenant; Langfuse is for engineers |
| 2026-10-18 | Transcripts read from the LangGraph checkpoint, not copied | One source of truth for messages; the turns table keeps only short previews |
| 2026-10-18 | Handoff = flag + Inbox, no live human takeover yet | Covers the real need (follow up with the customer) without a realtime agent console |
| 2026-10-18 | No repeated handoff, enforced in code | The router LLM kept classifying the customer's contact details as handoff; a deterministic rule is cheaper and certain |
| 2026-10-18 | Ownership check as a router-level dependency | Every current and future route under the prefix is protected by default |
| 2026-10-18 | Public slug page; chat/voice stay public by business id | Customers need no account; management needs one |
| 2026-10-18 | First signup claims pre-auth businesses | Migrates existing demo data without manual SQL |
| 2026-10-18 | Fixed-window rate limits in Redis, fail-open | Shared across replicas; availability over strictness for a customer-facing assistant |
| 2026-10-18 | Per-IP and per-business chat limits | IP stops one abuser; business limit protects each tenant's LLM budget |
| 2026-10-18 | Regex prompt-injection guardrail before the LLM, tuned on legit + attack cases | Zero cost/latency first line of defence; false positives block real customers, so tested both ways |
| 2026-10-18 | Langfuse Cloud (SDK v5) for tracing; self-host-compatible | Zero ops; laptop RAM too tight for self-hosted ClickHouse stack |
| 2026-10-18 | Trace ids propagated in A2A metadata | One turn = one trace across API + agents (distributed tracing) |
| 2026-10-18 | Chunk size 500 / overlap 100 (from 1000 / 150) | Eval at equal overlap: hybrid Hit@1 86% vs 82%, MRR 0.93 vs 0.90 |
| 2026-10-18 | Evals not in CI; run on demand, report committed | Paid/limited APIs + non-determinism; CI keeps deterministic tests |
| 2026-10-18 | Different model as judge (Groq) + rubric + structured output | Reduce self-preference bias; machine-readable scores |
| 2026-10-18 | Widget = script that injects an iframe to `/c/<slug>?embed=1` | Host page can't read/alter the chat (and vice versa); one line to install; loads chat lazily on first open |
| 2026-10-18 | Frame-deny headers on all pages except `/c/*` | Clickjacking protection for the dashboard; only the customer chat is embeddable |
| 2026-10-18 | No embedding fallback | Different embedding models produce incomparable vector spaces; would require re-embedding all chunks |
| 2026-10-17 | Commit identity = GitHub noreply email (repo-local) | Global git email is the work address; noreply links commits to yash6388 without exposing an email |
