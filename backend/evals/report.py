from evals.metrics import percentile


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def latency_line(ms: list[float]) -> str:
    if not ms:
        return "—"
    return f"p50 {percentile(ms, 50):.0f} ms · p95 {percentile(ms, 95):.0f} ms (n={len(ms)})"


def render(results: dict, meta: dict) -> str:
    out = [
        "# VoxDesk — Evaluation Report",
        "",
        f"- **Run:** {meta['started']} · duration {meta['duration_s']:.0f} s",
        f"- **Models:** {meta['models']}",
        f"- **Corpus:** {meta['corpus']}",
        *([f"- **Note:** {meta['notes']}"] if meta.get("notes") else []),
        "",
    ]

    if "retrieval" in results:
        out += [
            "## 1. Retrieval (does the right passage come back?)",
            "",
            "Same candidates, three rankings: vector only, keyword (full-text) only, and hybrid "
            "(RRF fusion). Compared at different chunk sizes.",
            "",
            "| Chunk size | Strategy | Hit@1 | Hit@3 | Hit@5 | MRR |",
            "|---|---|---|---|---|---|",
        ]
        for size, res in results["retrieval"].items():
            for mode in ("vector", "keyword", "hybrid"):
                s = res["summary"][mode]
                out.append(
                    f"| {size} | {mode} | {pct(s['hit@1'])} | {pct(s['hit@3'])} | "
                    f"{pct(s['hit@5'])} | {s['mrr']:.2f} |"
                )
        first = next(iter(results["retrieval"].values()))
        misses = [r for r in first["rows"] if not r["hybrid"] or r["hybrid"] > 3]
        if misses:
            out += ["", "Hybrid misses (relevant passage not in top 3):", ""]
            out += [
                f"- {r['question']} — vector rank {r['vector']}, keyword rank {r['keyword']}, "
                f"hybrid rank {r['hybrid']}"
                for r in misses
            ]
        out.append("")

    if "routing" in results:
        r = results["routing"]
        out += [
            "## 2. Routing (knowledge / booking / small talk)",
            "",
            f"**Accuracy: {pct(r['summary']['accuracy'])}** · "
            f"latency {latency_line(r['latencies_ms'])}",
            "",
            "| Expected → got | Count |",
            "|---|---|",
            *[f"| {k} | {v} |" for k, v in r["confusion"].items()],
        ]
        wrong = [row for row in r["rows"] if not row["ok"]]
        if wrong:
            out += ["", "Misrouted:", ""]
            out += [f"- “{w['message']}” → {w['got']} (expected {w['expected']})" for w in wrong]
        out.append("")

    if "answers" in results:
        a = results["answers"]
        s = a["summary"]
        out += [
            "## 3. Answers (grounded generation)",
            "",
            f"- **Fact accuracy:** {pct(s['fact_accuracy'])} (expected facts present)",
            f"- **Faithfulness (LLM judge, 1–5):** mean {s['mean_faithfulness']:.2f} · "
            f"{pct(s['faithful_rate (≥4)'])} scored ≥ 4",
            f"- **Correct refusals on unanswerable questions:** {pct(s['correct_refusals'])}",
            f"- **Latency:** {latency_line(a['latencies_ms'])}",
            *([f"- **Errored (excluded):** {s['errors']}"] if s.get("errors") else []),
            "",
            "| Question | Answer | Facts | Faithfulness | OK |",
            "|---|---|---|---|---|",
        ]
        for row in a["rows"]:
            if "error" in row:
                out.append(f"| {row['question']} | error: {row['error']} | — | — | ⚠️ |")
                continue
            answer = (
                (row.get("answer") or row.get("error", "")).replace("\n", " ").replace("|", "/")
            )
            facts = "—" if not row.get("answerable") else ("✅" if row.get("facts_ok") else "❌")
            faith = (
                row.get("faithfulness")
                if row.get("answerable")
                else ("refused ✅" if row.get("refused") else "did not refuse ❌")
            )
            out.append(
                f"| {row['question']} | {answer[:110]} | {facts} | {faith} | "
                f"{'✅' if row.get('ok') else '❌'} |"
            )
        out.append("")

    if "booking" in results:
        b = results["booking"]
        out += [
            "## 4. Booking agent (real LLM, fake tools — nothing is booked)",
            "",
            f"**Task success: {pct(b['summary']['task_success'])}** · "
            f"latency {latency_line(b['latencies_ms'])}"
            + (
                f" · errored (excluded): {b['summary']['errors']}"
                if b["summary"].get("errors")
                else ""
            ),
            "",
            "| Case | Tools called | Paused to confirm a booking | Checks | OK |",
            "|---|---|---|---|---|",
        ]
        for row in b["rows"]:
            checks = ", ".join(
                f"{k} {'✅' if v else '❌'}" for k, v in row.get("checks", {}).items()
            )
            tools = " → ".join(row.get("tools_called", [])) or row.get("error", "")
            booked = "yes" if row.get("booked") else "no"
            ok = "⚠️ error" if "error" in row else ("✅" if row["ok"] else "❌")
            out.append(f"| {row['case']} | {tools} | {booked} | {checks} | {ok} |")
        out.append("")

    return "\n".join(out)
