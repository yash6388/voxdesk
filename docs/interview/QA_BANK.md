# VoxDesk — Interview Question Bank

> Practice sheet: cover the answer, say yours out loud, then compare. Each answer is short on
> purpose — the topic files (01–10) have the depth. Answers use **real VoxDesk details and numbers**,
> which is what makes them convincing.

**Contents:** [Project](#a-the-project) · [Backend/FastAPI](#b-python--fastapi) ·
[RAG](#c-rag-embeddings--vector-search) · [LangGraph & agents](#d-langgraph--agents) ·
[MCP](#e-mcp) · [A2A & multi-agent](#f-a2a--multi-agent) · [Voice](#g-voice) ·
[LLM ops](#h-llm-operations-reliability-cost-latency) · [Security](#i-security--multi-tenancy) ·
[Testing & evaluation](#j-testing--evaluation) · [Infra](#k-infrastructure--devops) ·
[System design](#l-system-design) · [Stories](#m-behavioural--project-stories)

---

## A. The project

**1. What is VoxDesk, in one sentence?**
A multi-agent voice AI platform for small businesses: customers chat or talk to a business's agent,
which answers from the business's own documents (RAG) and books appointments through our MCP server,
with specialist agents coordinated over A2A.

**2. What's the architecture?**
Next.js frontend → FastAPI API running a LangGraph **supervisor** → delegates over **A2A** to a
**Knowledge agent** (hybrid RAG on pgvector) and a **Booking agent**, which calls booking tools on our
**MCP server**. Postgres stores everything (data, vectors, agent checkpoints); Redis does rate limits;
Langfuse traces every turn; voice is a WebSocket with local STT/TTS.

**3. What was the hardest part?**
Making the booking agent trustworthy: it invented a service id and a customer named "John Doe" in live
tests. Fixed with full recent context, a code guardrail that checks name/phone came from the customer,
id validation before asking the human, human confirmation, and a database constraint against double
booking.

**4. What would you do differently?**
Start agents in-process and split into services only when needed; store original uploaded files (so
re-chunking after the chunk-size change doesn't need re-uploads); add the evaluation suite earlier.

**5. What are you most proud of?**
Decisions backed by measurement: hybrid search and chunk size chosen by eval (Hit@1 82% → 86%,
MRR 0.90 → 0.93 at equal overlap),
the fallback model chosen by live latency/tool-calling tests, the circuit-breaker savings measured.

---

## B. Python & FastAPI

**6. Why FastAPI?**
Async-first for I/O-heavy LLM/DB work, Pydantic validation, automatic OpenAPI docs, clean dependency
injection.

**7. Why async?**
Most time is waiting on Gemini/Postgres; async lets one process serve many concurrent requests during
those waits.

**8. What is dependency injection in FastAPI and how did you use it?**
Endpoints declare what they need (`session: SessionDep`, `business: OwnedBusiness`); FastAPI builds and
cleans it up. Tests override dependencies (fake embedder, in-memory rate limiter); tenant isolation is
a router-level dependency.

**9. How do you run CPU-heavy work in async code?**
Off the event loop: `run_in_threadpool` for PDF parsing, `asyncio.to_thread` for Whisper/Kokoro.

**10. SSE vs WebSocket?**
SSE: one-way server push over HTTP — chat token streaming. WebSocket: bidirectional — voice (audio
both ways + interrupt messages).

**11. How do background tasks work and when would you use a queue instead?**
`BackgroundTasks` run after the response in-process (used for ingestion: 202 Accepted + status
polling). If the process restarts the job is lost — a queue (Celery/Arq/Redis) for durability and
scale.

**12. How do you manage database schema changes?**
Alembic migrations, reviewed by hand: added `CREATE EXTENSION vector/btree_gist`, server defaults
for new NOT NULL columns, 3-step add-backfill-enforce for `slug`, and a filter so autogenerate never
drops LangGraph's checkpoint tables.

**13. What's a common async SQLAlchemy pitfall?**
Lazy loading — accessing a relationship triggers hidden I/O → `MissingGreenlet`. Load explicitly
(`selectinload` / explicit `select`).

---

## C. RAG, embeddings & vector search

**14. What is RAG and why not fine-tune?**
Retrieve relevant passages, then answer only from them. Business facts change (prices, hours) — RAG
updates by re-uploading a document, cites sources, works per tenant; fine-tuning teaches style, not
reliable fresh facts.

**15. Walk through your ingestion pipeline.**
Upload (type/size validated) → 202 → background: extract text (pypdf in a thread) → recursive
character splitter (500 chars, 100 overlap) → Gemini embeddings (768-d, batches of 100,
`RETRIEVAL_DOCUMENT`) → chunks in Postgres with a vector and a generated tsvector → status `ready`.

**16. How did you choose the chunk size?**
Eval with overlap held at 100: 500 vs 1000 characters → hybrid Hit@1 86% vs 82%, MRR 0.93 vs 0.90
(vector-only 82% vs 64%); changed the default to 500. My first comparison also changed overlap (73%) —
caught it and re-ran controlled. Short fact-dense docs favour small chunks.

**17. Why chunk overlap?**
A fact on a boundary still appears whole in at least one chunk.

**18. What's an embedding?**
A vector representing meaning; similar meaning → nearby vectors. "Can I bring my car?" lands near
"free basement parking" despite sharing no words.

**19. Word2Vec vs what you used?**
Word2Vec = one static vector per word, no context. Gemini embeddings are contextual transformer
embeddings of whole passages.

**20. Why 768 dimensions?**
Gemini supports reduced dimensions with little quality loss; 768 cuts index size and search time vs
3072 — matters for voice latency.

**21. Cosine vs dot vs Euclidean?**
Cosine = angle only (standard for text); dot = cosine when vectors are normalised; Euclidean is
length-sensitive. pgvector `<=>` is cosine distance.

**22. Why pgvector instead of Qdrant/Pinecone?**
Postgres was already the system of record (bookings, checkpoints): one database, transactional
consistency, SQL tenant filtering. A dedicated vector DB when vectors dominate at very large scale.

**23. HNSW vs IVFFlat?**
HNSW: graph index, better recall/speed, no training, more memory. IVFFlat: clusters, needs training
data, faster build, lower recall unless probing more lists.

**24. What is hybrid search and how do you fuse results?**
Vector + Postgres full-text in one SQL query, fused with Reciprocal Rank Fusion:
score = Σ 1/(60 + rank). Rank-based, so no score normalisation between incompatible scales.

**25. Did hybrid actually help?**
Yes: Hit@1 86% hybrid vs 82% vector-only vs 77% keyword-only at 500-char chunks, on identical
candidates.

**26. Why does keyword search use OR instead of AND?**
`plainto_tsquery` ANDs every word; natural questions rarely have all words in one chunk, so `&` → `|`
and ranking favours more matches.

**27. How do you handle follow-up questions in retrieval?**
The router rewrites them into standalone queries using history ("And how long?" → "duration of
keratin treatment").

**28. How do you prevent hallucinated answers?**
Ground in retrieved context, require citations, explicitly allow "I don't know"; measured:
faithfulness 5.0/5 and correct refusals on unanswerable questions.

**29. Why no embedding fallback provider?**
Different embedding models produce incomparable vector spaces; switching means re-embedding everything.

**30. How would you improve retrieval next?**
Reranking (cross-encoder/LLM) over top-20, header-aware chunking, bigger golden set — all judged by
the same Hit@1/MRR.

---

## D. LangGraph & agents

**31. Why LangGraph instead of a single prompt or a free agent loop?**
Explicit, testable control flow (knowledge questions always retrieve first), plus checkpointing,
streaming and interrupts built in.

**32. How does memory work?**
Postgres checkpointer saves graph state after every node, keyed by `business_id:thread_id`; survives
restarts and works across instances.

**33. What's a reducer?**
How state updates merge — `messages` uses `add_messages` (append, de-duplicate by id). A test once
lost a reply because the fake reused the same message object (same id).

**34. How does routing work?**
A small model (flash-lite) with structured output returns `{intent, search_query}` in one call —
classification + query rewriting together; plain Python picks the next node. 100% on the routing eval.

**35. How do you stream from LangGraph?**
`astream` with `messages` (tokens), `updates` (node outputs, interrupts) and `custom` (events relayed
from remote agents via `get_stream_writer`).

**36. What is human-in-the-loop and how did you implement it?**
Write actions pause the graph with `interrupt()`; state is checkpointed; the UI shows a confirmation
card; `/chat/resume` continues with `Command(resume={"approved": …})`. Read-only tools don't ask.

**37. Why does nothing before `interrupt()` have side effects?**
On resume, LangGraph re-runs the node from the start; side effects before the interrupt would run twice.

**38. How do you limit context for long conversations?**
Sliding window of the last 10 messages for the router/answers; the booking agent sees the last 3 full
turns including tool results (to reuse real ids). Next: summarisation.

**39. The agent invented data. How did you stop it?**
Prompts weren't enough. Code guardrail: name/phone must appear in the customer's messages; ids
validated against the DB; invalid actions go back to the agent before a human sees them.

---

## E. MCP

**40. What is MCP?**
Model Context Protocol — a standard for AI apps to discover and call tools (and resources/prompts) in
a separate server over JSON-RPC (stdio or Streamable HTTP).

**41. Did you implement MCP?**
Both sides: a FastMCP server with 7 booking tools over Streamable HTTP (stateless, bearer auth), and
the booking agent consumes it via `langchain-mcp-adapters`. MCP Inspector/Claude Desktop can use it too.

**42. MCP vs function calling?**
Function calling = tool code inside one app. MCP = tools as a separate, independently deployed and
secured service, discovered at runtime, usable by any MCP client.

**43. stdio vs Streamable HTTP?**
stdio = local subprocess, one client (desktop tools). HTTP = network service, many clients, scalable —
needed for a multi-tenant SaaS.

**44. How does the MCP server know which business a call is for?**
`X-Business-Id` header on the authenticated connection — never a tool argument, so the LLM can't
choose or be tricked into another tenant. A test asserts no tool schema contains `business_id`.

**45. How did you design the tools?**
Small single-purpose tools; docstrings written for the model (formats, when to call); separate `date`
and `time` args (LLMs fill these more reliably than tz-aware datetimes); user-safe error messages.

**46. How do you prevent double booking?**
App-level availability check for a friendly message, plus a Postgres exclusion constraint on
`(business_id, tstzrange(start, end))` for confirmed bookings — atomic under concurrency; a test forces
the race and exactly one wins.

---

## F. A2A & multi-agent

**47. What is A2A?**
Agent2Agent protocol: agents publish Agent Cards (`/.well-known/agent-card.json`) and delegate tasks
over JSON-RPC with streaming, multi-turn tasks and states like `input-required`.

**48. MCP vs A2A?**
MCP connects an agent to tools; A2A connects agents to agents. The booking agent is an A2A server to
the supervisor and an MCP client to its tools.

**49. Does multi-agent mean separate servers?**
No — it's a design pattern, usually in-process (LangGraph nodes/subgraphs). Separate services are a
deployment choice for team ownership, scaling, permissions or interoperability.

**50. Why split VoxDesk's agents into services?**
Partly to demonstrate A2A; real reasons: least privilege (only the booking agent holds the MCP write
key), independent failure (bookings down ≠ questions down), different load. In an early product I'd
start in-process.

**51. How does confirmation work across agents?**
Booking agent's graph interrupts → its A2A task goes `input-required` with the actions → supervisor
stores the pending task and interrupts its own graph → UI asks → resume sends `{"approved": true}` on
the **same A2A task**.

**52. How do you stream a remote agent's answer to the browser?**
Agent streams artifact chunks over A2A (SSE) → supervisor forwards via LangGraph's custom stream →
API emits SSE tokens.

**53. What's in an Agent Card?**
Name, description, version, endpoint + protocol binding, capabilities (streaming), skills with
examples, input/output modes, security schemes.

**54. What did prototyping the A2A SDK teach you?**
v1.2 rules not in tutorials: the first artifact chunk must create the artifact (append=False), and
request metadata isn't persisted across messages (send business info every time).

---

## G. Voice

**55. Walk me through a voice turn.**
Browser records webm/opus while the button is held → WebSocket → decode to 16 kHz mono → faster-whisper
→ supervisor → stream tokens → split into sentences → Kokoro synthesises each in a pipelined speaker
task → audio frames back → browser plays in order.

**56. Local models or cloud?**
Local by default (faster-whisper + Kokoro int8: free, private, no quotas), ElevenLabs by one env var —
same `STT`/`TTS` interface.

**57. Did you need PyTorch?**
No — faster-whisper runs on CTranslate2, Kokoro on ONNX Runtime; inference runtimes, not training
frameworks. Kept the image smaller and CPU inference faster.

**58. How do you reduce voice latency?**
Sentence-level TTS pipelined with generation, model warm-up at startup, int8 models, no "thinking"
pass, short answers by prompt; measure time to first audio per turn.

**59. How do you confirm a booking by voice?**
Read the action aloud; classify the reply conservatively — any "no" wins, ambiguity re-prompts — then
resume the same paused graph as a click would.

**60. How does barge-in work?**
Client stops playback and sends `interrupt`; server cancels the asyncio task running the turn (LLM
streaming and TTS stop).

**61. A dependency bug you hit?**
faster-whisper called PyAV with an argument removed in PyAV 19; pinning failed (no wheel). Decoded audio
myself with PyAV + `AudioResampler` and passed Whisper a NumPy array.

---

## H. LLM operations: reliability, cost, latency

**62. What if your LLM provider is down or rate-limited?**
Automatic fallback to a second OpenAI-compatible provider (Groq `gpt-oss-120b`), no retries when a
backup exists, and a circuit breaker that skips the primary for 5 minutes after 3 outage errors.

**63. How did you pick the fallback model?**
Live tests on the account's available models: gpt-oss-120b passed plain answer (247 ms), tool calling
(297 ms) and structured output (596 ms); another model failed on a free-tier output cap.

**64. Explain the circuit breaker.**
Closed → open after N outage errors (calls fail instantly → fallback) → half-open trial after cooldown
→ closed on success. Counts only 429/5xx/timeouts, not 400s.

**65. A bug in it?**
LangChain's async path calls the sync path in a thread; both were guarded, so one failure counted
twice. Fixed with a context flag; found by tests.

**66. How do you control cost?**
Small model for routing, short answers, history window, top-5 chunks, rate limits per business, no
thinking pass; tracing shows tokens per call.

**67. How do you know which model answered?**
Langfuse traces record the model name on every LLM call.

**68. What's the difference between a 429 and a 400 operationally?**
429 = provider capacity/quota (retry later, fail over, trip breaker); 400 = our bad request (fix the
code; retrying won't help).

---

## I. Security & multi-tenancy

**69. How do owners authenticate?**
Argon2id password hashing; JWT (HS256, 7 days) in an httpOnly, SameSite=Lax cookie; Bearer header also
accepted for API clients.

**70. Why a cookie instead of localStorage?**
httpOnly cookies can't be read by JavaScript → XSS can't steal the session; SameSite=Lax blocks
cross-site POSTs (CSRF).

**71. How do you enforce tenant isolation?**
Router-level dependency: the signed-in user must own the business in the path; otherwise **404, not
403**, so ids can't be probed. In agents, tenant = MCP connection header.

**72. How do you prevent user enumeration on login?**
Same error message and same work (dummy Argon2 verify) whether or not the email exists.

**73. Rate limiting design?**
Redis fixed-window counters (INCR + EXPIRE NX), shared across replicas; per IP, per business, per user;
429 + Retry-After; fails open if Redis is down.

**74. How do you defend against prompt injection?**
Regex guardrails before any LLM call (tested both ways: 8 attacks caught, 5 legit messages allowed after
fixing 2 false positives) — but mainly architecture: the model can't choose tenants, can't write
without confirmation, tool inputs are validated, the DB enforces invariants.

**75. What stops a misconfigured production deploy?**
The API refuses to start in production with the dev JWT secret (< 32 chars) or insecure cookies.

---

## J. Testing & evaluation

**76. How do you test LLM applications?**
Two layers: deterministic tests (117, ~8 s, fake LLMs/embedder, real Postgres + Redis) on every push;
an evaluation suite with real models on demand.

**77. Why a real database in tests?**
The core logic is SQL (hybrid search, exclusion constraint); mocks would test nothing real.

**78. How do you test a race condition?**
Bypass the app-level check and fire two bookings concurrently; assert the DB constraint lets exactly
one succeed.

**79. How do you test the A2A protocol?**
In-process with `httpx.ASGITransport`: the real SDK client talks HTTP to the real agent app — card
discovery, streaming, input-required → resume.

**80. What's in your eval suite?**
Retrieval (Hit@1/3/5, MRR; vector vs keyword vs hybrid; chunk sizes), routing accuracy + confusion
matrix, answer fact accuracy + LLM-judge faithfulness + refusal rate, booking agent task success
with fake tools, latency p50/p95.

**81. Results?**
Hybrid@500: Hit@1 86%, Hit@3 100%, MRR 0.93 · routing 100% · faithfulness 5.0/5 · refusals 100% ·
booking task success 100%.

**82. What did the eval catch?**
Chunk-size improvement; full-width `【2】` citations from the fallback model (voice would read "2"); an
evaluator whitespace bug; rate-limit errors scored as failures; a mislabelled golden case.

**83. Hit@k vs MRR vs precision vs recall?**
Hit@k: correct passage in top k. MRR: average 1/rank of first correct. Precision@k: share of top k
that's relevant. Recall@k: share of all relevant passages found (= Hit@k with one relevant passage).

**84. What are p50 and p95?**
Median and 95th-percentile latency: typical vs slow-tail experience; averages hide both.

**85. LLM-as-judge pitfalls?**
Verbosity/position/self-preference bias, cost, needs calibration. Mitigated with a rubric, structured
output listing unsupported claims first, temperature 0, a different judge model.

**86. Why isn't the eval in CI?**
Paid/limited API calls and non-determinism; run before prompt/model/retrieval changes; reports
committed.

---

## K. Infrastructure & DevOps

**87. How is it deployed/run?**
Docker: one backend image runs as API, MCP and both agents (different commands); standalone Next.js
image; Compose profile starts 7 services with healthcheck-gated ordering; migrations on API start.

**88. Why one image for four services?**
Same code; built once, consistent everywhere; only the command differs.

**89. Liveness vs readiness?**
`/health` = process alive (restart if not). `/health/services` = DB, MCP, agents reachable, checked in
parallel with 2 s timeouts (stop routing if not).

**90. What does CI do?**
Backend lint + format check + tests against real pgvector Postgres and Redis service containers;
frontend lint + build; Docker builds of both images.

**91. How do you observe it?**
Langfuse: one trace per turn across API and agents (trace id propagated in A2A metadata) — router,
LLM calls with model/tokens, MCP tools, retrieval, STT/TTS spans.

---

## L. System design

**92. How would you scale to 10,000 businesses?**
Stateless API/agents/MCP behind load balancers (state in Postgres/Redis); DB task store for A2A;
ingestion via a queue; read replicas; partition chunks by tenant or move vectors to a dedicated store if
they dominate; per-tenant rate limits and quotas; cache frequent answers.

**93. Where are the bottlenecks?**
LLM latency/quota (fallbacks, breaker, smaller models), TTS on CPU (GPU or cloud TTS), embedding
throughput at ingestion (batching, queue), Postgres connections (pooling).

**94. How would you add phone calls?**
Twilio Media Streams as another transport adapter on the same voice pipeline (audio in → STT → agents →
TTS → audio out).

**95. How would you add multiple staff/resources?**
A `resources` table; bookings reference a resource; the exclusion constraint moves to
`(resource_id, time range)`; availability = any free resource.

**96. Single points of failure today?**
Postgres (managed HA/replicas), in-memory A2A task store (DB task store), one Redis (fail-open
already), LLM provider (fallback + breaker done).

---

## M. Behavioural / project stories

**97. Tell me about a bug you found.**
Live testing showed the booking agent inventing "John Doe" despite prompt rules → added a deterministic
grounding guardrail; "prompts are requests, not guarantees".

**98. Tell me about a decision you made with data.**
Chunk size 1000 → 500 after the retrieval eval (Hit@1 82% → 86%, MRR 0.90 → 0.93, overlap held
constant); fallback model chosen by live tests.

**99. Tell me about a time you were wrong.**
Two: I labelled a golden case unanswerable when the FAQ answered it (the agent was right); and my first
chunk-size comparison changed overlap too, inflating the gap from 4 to 13 points. Fixed both and
reported the controlled numbers.

**100. How do you work with AI coding tools?**
Use them to move fast, but own every decision: prototype unfamiliar SDKs first, read the actual API
before writing code, verify with tests and live runs, and measure before claiming improvements.
