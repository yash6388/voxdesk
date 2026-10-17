# 10 — Evaluation: How Do You Know Your AI Works?

> Phase 5, Step 5. The single most important question in AI-engineer interviews. VoxDesk answers it
> with a repeatable evaluation suite, real numbers, and decisions made from those numbers.

---

## 1. Plain English first

Unit tests (117 of them) prove the **code** works: routing logic, SQL, auth, guardrails. They use fake
LLMs, so they say nothing about whether the **AI** gives good answers.

An **evaluation suite** answers a different question: *with real models and realistic data, how good
are the outputs?* You can't assert one exact string (LLMs vary), so you measure **rates and scores**
over many test cases and track them over time.

```
golden dataset (questions + known right answers)
        │
        ▼
run the REAL system (real embeddings, real LLMs)  ──►  score each output  ──►  report (numbers)
                                                         │
                                       exact checks · rank metrics · LLM-as-judge
```

**Run it:** `cd backend && uv run python -m evals.run` → writes `backend/evals/reports/latest.md`.
`--suites retrieval` runs only retrieval (no chat-LLM calls, just embeddings). Each run builds a
**temporary business** from `samples/*.md` and **deletes it afterwards** — real data is never touched.

---

## 2. The golden dataset

**File:** `backend/evals/data/golden.json` — hand-written cases with known correct answers.

| Suite | Cases | What a case contains |
|---|---|---|
| Retrieval | 22 | Question + phrase(s) the correct passage must contain |
| Routing | 13 | Conversation (incl. 2 follow-ups needing history) + expected intent |
| Answers | 10 | Question + facts that must appear, or "unanswerable" (should refuse) |
| Booking | 5 | Customer request + expected tool arguments, or "must NOT book" |

Design choices worth mentioning:
- **Corpus of 4 documents** (prices/policies, FAQ, aftercare, team). One 3-chunk document would make
  retrieval trivially "100%" — similar passages must **compete** for the metric to mean anything.
- Questions mix **paraphrases** ("Can I bring my car?" → parking), **exact terms** ("keratin",
  "UPI"), facts in **different documents**, and **negatives** (unanswerable questions, impossible
  bookings).
- Retrieval relevance = "top passage contains an expected phrase" — robust to how text is chunked.

> **Golden sets have bugs too.** I labelled "What is the Wi-Fi password?" unanswerable, but the FAQ
> says "Ask at reception for the password" — the agent's answer was correct and my label was wrong.
> Fixed it and added a genuinely unanswerable case (eyelash extensions).

---

## 3. Metrics, explained (with examples)

### Hit@k (a.k.a. Recall@k for single-answer questions)
"Is the correct passage somewhere in the top *k* results?" Averaged over questions.

Example with 4 questions whose correct passage was found at ranks 1, 2, not found, 4:
- Hit@1 = 1/4 = **25%** (only the first question had it at #1)
- Hit@3 = 2/4 = **50%**
- Hit@5 = 3/4 = **75%**

Why it matters for RAG: the LLM only sees the top 5 chunks. If the right passage isn't in them, the
answer *can't* be right (or it hallucinates). **Hit@5 bounds answer quality.** Hit@1 matters for
latency/cost (fewer chunks needed) and for small context windows.

### MRR — Mean Reciprocal Rank
For each question take **1 / rank** of the first correct result (0 if not found), then average.
Same example: (1/1 + 1/2 + 0 + 1/4) / 4 = **0.44**.
MRR rewards putting the right answer **near the top**, not just "somewhere in the top k".
1.0 = always first; 0.5 ≈ typically second.

### Precision / Recall (know the difference)
- **Precision@k**: of the k results, how many are relevant? (purity of results)
- **Recall@k**: of all relevant passages, how many are in the top k? (coverage)
With one relevant passage per question, Recall@k = Hit@k — which is why we report Hit@k.
NDCG is a further metric that handles multiple relevance grades; overkill here.

### Accuracy + confusion matrix (routing)
Accuracy = correct / total. The **confusion matrix** shows *which* mistakes happen
(e.g. "booking → knowledge" ×2 would mean booking requests are being answered as questions —
a very different bug from small talk being misrouted).

### Fact accuracy
Does the answer contain the expected facts? Each fact is a group of acceptable spellings, e.g.
`["6,500", "6500"]`; all groups must match. Deterministic and cheap.

### Faithfulness (via LLM-as-judge) — see §4
Is every claim in the answer **supported by the retrieved context**? Scored 1–5.

**Faithfulness ≠ correctness:** an answer can be faithful to wrong context, or correct but
unsupported (from the model's memory). For a business assistant we want both: right facts
(fact accuracy) **and** no claims beyond the documents (faithfulness).

### Correct refusal rate
On questions the documents can't answer, the right behaviour is "I don't have that information" —
not a confident guess. We measure how often the agent refuses correctly. **This is hallucination
measurement**: a refusal rate below 100% means it invented answers.

### Task success (booking agent)
For the agent: did it do the right thing end to end? For "book" cases: paused for confirmation with
the right **service, date, time, name and phone**. For "don't book" cases: **no** booking attempt.

### Latency percentiles: p50, p95
- **p50 (median):** half the requests are faster than this — the *typical* experience.
- **p95:** 95% are faster — the *slow tail* 1 in 20 users gets.
- Why not the average? One 30-second outlier drags the mean up and hides that most requests are
  fast; or a fast majority hides a terrible tail. Percentiles show both. SLOs are written as
  "p95 < 1.5 s", not "average < 1 s". (p99 for large traffic.)

---

## 4. LLM-as-judge

**File:** `backend/evals/judge.py`

For open-ended text, exact matching is too brittle ("₹6,500" vs "six thousand five hundred rupees").
So a **second LLM** grades the answer against a rubric:

- **Inputs:** question, the retrieved context, the answer.
- **Rubric:** faithful = every factual claim (prices, times, policies, names) is supported by the
  context; politeness isn't a claim; no outside knowledge. Score 1–5 with defined meanings.
- **Structured output:** `{unsupported_claims: [...], score: 1-5, reasoning}` — the judge must
  **list the unsupported claims before scoring** (reasoning before verdict improves reliability)
  and its output is machine-readable.
- **A different model as judge** (Groq `gpt-oss-120b`) where possible, to reduce self-preference
  bias (models tend to rate their own outputs higher).

Known limitations (say these — it shows maturity):
- Judges have biases (verbosity, position, self-preference) → use a rubric, structured output,
  temperature 0, and a different model.
- The judge needs validating: spot-check a sample of its scores by hand (calibration).
- It costs tokens/latency → run it in the eval suite, not on every production request (or sample).

> "I use deterministic checks where possible — exact facts, ranks, tool arguments — and an
> LLM-as-judge only for faithfulness, with a rubric, structured output that lists unsupported claims
> before the score, and a different model from the one being judged."

---

## 5. Results

Run on 2026-10-18 (models: answers/agent on Groq `gpt-oss-120b` because Gemini's free quota was
exhausted, router `gemini-2.5-flash-lite` with fallback, embeddings `gemini-embedding-001`).
Full report: `backend/evals/reports/latest.md`.

### 5.1 Retrieval — strategy × chunk size

Final run (all at **100-character overlap**):

| Chunk size | Strategy | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---|---|---|---|---|
| 500 | vector only | 82% | 95% | 100% | 0.90 |
| 500 | keyword only | 77% | 95% | 95% | 0.86 |
| **500** | **hybrid (RRF)** | **86%** | **100%** | **100%** | **0.93** |
| 1000 | vector only | 64% | 86% | 95% | 0.75 |
| 1000 | keyword only | 64% | 91% | 95% | 0.78 |
| 1000 | hybrid (RRF) | 82% | 95% | 100% | 0.90 |

Earlier run: 1000 characters with **150** overlap → hybrid Hit@1 **73%**, MRR 0.85.

**How the strategy comparison is fair:** one hybrid query per question returns each chunk's
*semantic rank*, *keyword rank* and *fused order* — so all three strategies are ranked over
**identical candidates**.

**Observation 1 — hybrid beats both single strategies at every setting.**
At 500: Hit@1 86% vs 82% (vector) and 77% (keyword); MRR 0.93 vs 0.90 / 0.86. At 1000 the gap is even
larger: 82% vs 64% / 64%. Vector and keyword fail on *different* questions (paraphrases vs exact
terms), so fusing them wins. Measured proof for the Phase 1 design choice.

**Observation 2 — smaller chunks are better here (by a modest, real margin).**
Same overlap: hybrid Hit@1 **82% → 86%**, Hit@3 **95% → 100%**, MRR **0.90 → 0.93** going from 1000 to
500 characters. Why: these documents are lists of short, distinct facts (prices, policies, staff). A
1000-character chunk mixes several topics, so its embedding is a blurry average; a 500-character chunk
is about one topic, so the right one ranks first more often. Single-strategy results show the same
effect more strongly (vector Hit@1 64% → 82%).

**Observation 3 — overlap matters too, and my first comparison was confounded.**
My first run compared 500/100 against 1000/**150** (73%) — two variables changed at once, which
exaggerated the gap (13 points instead of 4). The final run holds overlap at 100 for both. Lesson:
**change one variable at a time**; I report the controlled numbers, not the more impressive ones.

**Decision — production chunk size 1000 → 500, overlap 150 → 100** (`app/config.py`, evidence in the
comment). Trade-off: smaller chunks mean more chunks to embed/store and less surrounding context per
chunk — fine for short business documents; long narrative documents might prefer larger chunks or
header-aware splitting. (Existing documents keep their old chunks until re-uploaded.)

> "I didn't guess the chunk size. I ran a retrieval eval across chunk sizes and three retrieval
> strategies. With overlap held constant, 500-character chunks with hybrid search gave the best
> results — Hit@1 86% vs 82%, MRR 0.93 vs 0.90 — so I changed the production default. My first run
> had accidentally changed the overlap too, which inflated the gap; I caught it and re-ran a
> controlled comparison."

### 5.2 Routing
**Accuracy 100%** (13/13), including both follow-ups that only make sense with history
("3pm, I'm Asha…" → booking; "And how long does it take?" → knowledge). Routing latency p50
330–630 ms across runs.

### 5.3 Answers
- **Faithfulness 5.00 / 5** — every answer fully supported by its context (judge found no
  unsupported claims).
- **Fact accuracy 100%** after fixing an evaluator bug (below).
- **Correct refusals 100%** (3/3: tattoos, laser hair removal, eyelash extensions — "I don't have
  information about … Would you like me to connect you with a staff member?") — no invented services.
- The relabelled Wi-Fi case: "just ask at the reception and they'll give it to you" — correct, faithful
  (5/5).

### 5.4 Booking agent
**Task success 100%** on completed cases: correct service, date (resolved from "Wednesday 21
October"), time, name and phone; and it **never** booked when details were missing, the time
wasn't free, or the salon was closed — it asked or offered alternatives instead.
Tool path every time: `list_services → check_availability` before any booking attempt.

### 5.5 Latency (and why the eval numbers aren't the real latency)
Answer/agent latency in the eval ran 9–18 s. Investigation: Groq answered a single request in
**~270 ms**, but its response headers showed the **per-minute token budget nearly exhausted** — the
eval's back-to-back, context-heavy calls hit the free tier's tokens-per-minute cap, and most of the
time was **waiting on rate-limit backoff**. The report now states this explicitly. Real latency is
measured per turn in the app (Inspector / Voice page) and in Langfuse traces.

> Lesson: investigate before concluding. "The model is slow" would have been the wrong diagnosis.

---

## 6. What the evaluation caught (great interview stories)

| # | Finding | Type | Fix |
|---|---|---|---|
| 1 | 500-char chunks beat 1000 (Hit@1 86% vs 82%, MRR 0.93 vs 0.90, same overlap) | Product improvement | Changed production default to 500/100 |
| 1b | First comparison changed chunk size **and** overlap (73% figure) | **Experiment-design flaw** | Re-ran with overlap held constant; report controlled numbers |
| 2 | Groq's `gpt-oss` writes citations as `【2】`, not `[2]` → UI chips broken, **voice would read "2" aloud** | Real product bug (only appears on the fallback model) | Accept both formats in TTS cleanup + UI; prompt asks for square brackets |
| 3 | "50 %" (with a space) scored as a missing fact | **Evaluator bug** | Normalise whitespace / NBSP before matching (+ unit tests for the metrics) |
| 4 | Rate-limit errors counted as wrong answers | **Evaluator bug** | Retry rate limits patiently; report errored cases separately, excluded from scores |
| 5 | "Wi-Fi password" labelled unanswerable, but the FAQ answers it | **Golden-set label bug** | Relabelled; added a truly unanswerable case |
| 6 | 9–18 s latency | Measurement artefact (free-tier TPM cap) | Diagnosed via headers; documented in the report |

Takeaways:
- **Evaluate every model you serve** — finding #2 only exists on the fallback model.
- **The evaluator and the dataset are code/data that need testing and review too** (#3, #4, #5).
- **Measure, then decide** (#1), **control your variables** (#1b), and **diagnose before concluding**
  (#6).

---

## 7. How the suite is built (for "walk me through it")

- `evals/setup.py` — temporary business: 4 docs ingested with real Gemini embeddings at a given
  chunk size, 3 services, opening hours; deleted in `finally`.
- `evals/suites.py`
  - **retrieval:** one hybrid query per question → ranks for vector / keyword / hybrid → Hit@k, MRR.
  - **routing:** the production `classify()` function with the real router model.
  - **answers:** the production `answer_messages()` prompt + real chat model → facts, refusals,
    judge.
  - **booking:** the real booking graph + real LLM + **fake tools** (Monday closed, 14:00 never free);
    a booking "happens" if the graph pauses for confirmation — so **nothing is ever booked**.
  - `patiently()` retries only rate-limit errors.
- `evals/judge.py` — rubric + structured `Judgement`.
- `evals/metrics.py` — Hit@k, MRR, percentiles, fact matching, refusal detection (unit-tested).
- `evals/report.py` → Markdown report + JSON for tracking over time.
- Production code was refactored so evals call **the same functions** (`classify`,
  `answer_messages`) — evaluating a copy of the logic would prove nothing.

**Not in CI on purpose:** it calls paid/limited APIs and is non-deterministic. CI runs the 117
deterministic tests on every push; the eval runs on demand — before changing a prompt, model, chunk
size or retrieval setting — and its report is committed so changes are reviewable.

---

## 8. Next steps (if asked "what would you add?")

1. **Reranking experiment** (cross-encoder or LLM reranker over top-20), judged by the same Hit@1/MRR.
2. **Bigger golden set** + generating candidate questions with an LLM, then human review.
3. **Track metrics over time** (Langfuse datasets/experiments or a CSV in CI artifacts); alert on
   regressions.
4. **Online evaluation:** sample production traces and score them with the judge; thumbs up/down
   feedback in the UI.
5. **End-to-end multi-turn booking evals** (customer simulator LLM) and **voice evals** (WER for STT).
6. **Judge calibration:** hand-label 30 answers, measure agreement with the judge.

---

## Q&A

**Q: How do you evaluate a RAG system?**
A: Separately evaluate retrieval and generation. Retrieval: a golden set of questions with the
passage that should come back, measured with Hit@k and MRR. Generation: fact accuracy with
deterministic checks, faithfulness with an LLM judge, and refusal rate on unanswerable questions.
Then end-to-end task metrics for agents.

**Q: What's Hit@k / MRR?**
A: Hit@k: share of questions whose correct passage is in the top k. MRR: average of 1/rank of the
first correct result — it rewards ranking the right passage near the top.

**Q: How did you choose your chunk size?**
A: Empirically: ran the retrieval eval at 500 and 1000 characters with the same overlap; 500 gave
hybrid Hit@1 86% vs 82% and MRR 0.93 vs 0.90 (vector-only: 82% vs 64%), so I changed the default —
these docs are dense lists of distinct facts, so smaller chunks keep each embedding about one topic.
My first run also changed overlap, which inflated the gap; I re-ran it controlled.

**Q: Did hybrid search actually help?**
A: Yes, measured: at 500 characters Hit@1 was 86% hybrid vs 82% vector-only and 77% keyword-only,
on identical candidates.

**Q: What is LLM-as-judge and what are its pitfalls?**
A: Using an LLM with a rubric to grade outputs that can't be string-matched. Pitfalls: verbosity,
position and self-preference bias, cost, and it needs calibrating against human labels. I mitigate
with a strict rubric, structured output listing unsupported claims before the score, temperature 0,
and a different model as judge.

**Q: How do you measure hallucination?**
A: Faithfulness (claims supported by retrieved context, via the judge) and the correct-refusal rate
on questions the documents can't answer.

**Q: p50 vs p95 — why not average latency?**
A: p50 is the typical request, p95 the slow tail; averages hide outliers or are skewed by them.
SLOs are set on percentiles.

**Q: How do you evaluate an agent that takes actions?**
A: Run the real agent with fake tools that record calls and can't cause side effects; check it
called the right tool with the right arguments, and that it refuses to act when it shouldn't
(missing details, unavailable time, closed day). Pausing for confirmation is the "action" signal.

**Q: Your eval said answers take 9–18 s. Is the model slow?**
A: No — single calls took ~270 ms; the rate-limit headers showed the free tier's per-minute token cap
was exhausted, so the eval was waiting on backoff. I documented it rather than reporting a misleading
number.

**Q: Why isn't the eval in CI?**
A: It costs real API calls and is non-deterministic. CI runs deterministic tests every push; the
eval runs before prompt/model/retrieval changes, and the report is committed for review.
