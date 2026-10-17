import re
import statistics


def first_relevant_rank(contents: list[str], expect_any: list[str]) -> int | None:
    """1-based rank of the first passage containing any expected phrase (case-insensitive)."""
    needles = [e.lower() for e in expect_any]
    for rank, content in enumerate(contents, start=1):
        if any(n in content.lower() for n in needles):
            return rank
    return None


def hit_at(ranks: list[int | None], k: int) -> float:
    """Share of questions whose relevant passage is in the top k."""
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def mrr(ranks: list[int | None]) -> float:
    """Mean Reciprocal Rank: 1 if the answer is always first, 0.5 if always second…"""
    return sum(1 / r for r in ranks if r) / len(ranks) if ranks else 0.0


def normalise(text: str) -> str:
    """Lowercase, unify (non-breaking) spaces and drop the space in "50 %" — so formatting
    differences don't count as wrong facts. (An evaluator bug found in the first run.)"""
    text = text.lower().replace("\u00a0", " ").replace("\u202f", " ")
    return re.sub(r"\s+%", "%", text)


def includes_all_groups(text: str, groups: list[list[str]]) -> bool:
    """Every group must match at least one of its alternatives, e.g. [["6,500", "6500"]]."""
    lowered = normalise(text)
    return all(any(alt.lower() in lowered for alt in group) for group in groups)


REFUSAL_MARKERS = [
    "don't have",
    "do not have",
    "not sure",
    "couldn't find",
    "can't find",
    "no information",
    "don't offer",
    "do not offer",
    "connect you",
    "our staff",
    "ask at reception",
]


def is_refusal(text: str) -> bool:
    lowered = text.lower().replace("’", "'")
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(p) - 1]
