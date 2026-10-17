"""The evaluator is code too — and its first run had a bug ("50 %" ≠ "50%")."""

from evals.metrics import first_relevant_rank, hit_at, includes_all_groups, is_refusal, mrr


def test_ranking_metrics():
    ranks = [1, 2, None, 4]
    assert hit_at(ranks, 1) == 0.25
    assert hit_at(ranks, 3) == 0.5
    assert mrr(ranks) == (1 + 0.5 + 0 + 0.25) / 4


def test_first_relevant_rank_is_case_insensitive():
    assert first_relevant_rank(["a", "Free PARKING here"], ["free parking"]) == 2
    assert first_relevant_rank(["nothing"], ["parking"]) is None


def test_fact_matching_ignores_formatting_differences():
    assert includes_all_groups("charged 50 % of the price", [["50%"]])
    assert includes_all_groups("costs ₹6,500", [["6,500", "6500"]])
    assert includes_all_groups("open 10 AM to 6 PM", [["10"], ["6"]])
    assert not includes_all_groups("costs ₹5,000", [["6,500", "6500"]])


def test_refusal_detection():
    assert is_refusal("I’m sorry, I don’t have information about tattoos.")
    assert not is_refusal("Yes, we accept UPI.")
