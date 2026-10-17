# VoxDesk — Evaluation Report

- **Run:** 2026-10-18T03:03:13 · duration 194 s
- **Models:** answers/agent: openai/gpt-oss-120b → gemini-2.5-flash · router: gemini-2.5-flash-lite (+fallback) · judge: openai/gpt-oss-120b · embeddings: gemini-embedding-001
- **Corpus:** 4 sample documents · 22 retrieval, 13 routing, 10 answer, 5 booking cases
- **Note:** Latency on free-tier providers includes rate-limit waits (Groq's per-minute token cap); measured single-call model latency is ~0.3 s.

## 1. Retrieval (does the right passage come back?)

Same candidates, three rankings: vector only, keyword (full-text) only, and hybrid (RRF fusion). Compared at different chunk sizes.

| Chunk size | Strategy | Hit@1 | Hit@3 | Hit@5 | MRR |
|---|---|---|---|---|---|
| 500 | vector | 82% | 95% | 100% | 0.90 |
| 500 | keyword | 77% | 95% | 95% | 0.86 |
| 500 | hybrid | 86% | 100% | 100% | 0.93 |
| 1000 | vector | 64% | 86% | 95% | 0.75 |
| 1000 | keyword | 64% | 91% | 95% | 0.78 |
| 1000 | hybrid | 82% | 95% | 100% | 0.90 |

## 2. Routing (knowledge / booking / small talk)

**Accuracy: 100%** · latency p50 632 ms · p95 853 ms (n=13)

| Expected → got | Count |
|---|---|
| booking → booking | 5 |
| knowledge → knowledge | 5 |
| smalltalk → smalltalk | 3 |

## 3. Answers (grounded generation)

- **Fact accuracy:** 100% (expected facts present)
- **Faithfulness (LLM judge, 1–5):** mean 5.00 · 100% scored ≥ 4
- **Correct refusals on unanswerable questions:** 100%
- **Latency:** p50 682 ms · p95 24736 ms (n=10)

| Question | Answer | Facts | Faithfulness | OK |
|---|---|---|---|---|
| How much does a keratin treatment cost? | A keratin smoothing treatment costs ₹6,500. [2] | ✅ | 5 | ✅ |
| What are your opening hours on Sunday? | We’re open on Sunday from 10:00 AM to 6:00 PM. [1] | ✅ | 5 | ✅ |
| What happens if I cancel less than 24 hours before my appointment? | If you cancel within 24 hours of your appointment, you’ll be charged 50 % of the service price [1]. | ✅ | 5 | ✅ |
| How long should I wait before washing my hair after keratin? | You should wait 72 hours before washing your hair after a keratin smoothing treatment. [1] | ✅ | 5 | ✅ |
| Do students get a discount? | Yes—students receive 10% off haircuts from Tuesday to Thursday with a valid college ID (cannot be combined wit | ✅ | 5 | ✅ |
| Is there parking? | Yes, we have free parking for up to 6 cars in the building’s basement. [1] | ✅ | 5 | ✅ |
| Do you do tattoos? | I’m sorry, I don’t have information about tattoo services. Would you like me to connect you with a staff membe | — | refused ✅ | ✅ |
| Do you offer laser hair removal? | I’m sorry, I don’t have information about laser hair removal. Would you like me to connect you with a staff me | — | refused ✅ | ✅ |
| What is the Wi-Fi password? | I don’t have the password on hand—just ask at the reception and they’ll give it to you. | ✅ | 5 | ✅ |
| Do you offer eyelash extensions? | I’m sorry, I don’t have information about eyelash extensions. Would you like me to connect you with a staff me | — | refused ✅ | ✅ |

## 4. Booking agent (real LLM, fake tools — nothing is booked)

**Task success: 100%** · latency p50 14157 ms · p95 30558 ms (n=5)

| Case | Tools called | Paused to confirm a booking | Checks | OK |
|---|---|---|---|---|
| complete request is booked (after confirmation) | list_services → check_availability | yes | books ✅, service ✅, date ✅, time ✅, name ✅, phone ✅ | ✅ |
| second service, different day | list_services → check_availability | yes | books ✅, service ✅, date ✅, time ✅, name ✅, phone ✅ | ✅ |
| missing name and phone → asks instead of booking | list_services → check_availability | no | books ✅ | ✅ |
| requested time not free → doesn't book it | list_services → check_availability | no | books ✅ | ✅ |
| closed day → doesn't book | list_services → check_availability | no | books ✅ | ✅ |
