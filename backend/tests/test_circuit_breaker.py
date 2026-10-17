import pytest
from langchain_core.language_models import GenericFakeChatModel

from app import circuit_breaker
from app.circuit_breaker import CircuitBreaker, CircuitBreakerMixin, CircuitOpenError
from app.config import get_settings
from app.llm import _ordered, with_fallback
from tests.fakes import replies


class RateLimited(Exception):
    code = 429


class BadRequest(Exception):
    code = 400


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def fresh_breakers():
    circuit_breaker._breakers.clear()
    yield
    circuit_breaker._breakers.clear()


# ---------- the state machine ----------


def test_opens_after_threshold_and_fails_fast():
    clock = FakeClock()
    breaker = CircuitBreaker("gemini", failure_threshold=3, cooldown_seconds=300, clock=clock)

    for _ in range(2):
        breaker.record_failure(RateLimited())
    assert breaker.state == "closed"
    breaker.check()  # still allowed

    breaker.record_failure(RateLimited())
    assert breaker.state == "open"
    with pytest.raises(CircuitOpenError):
        breaker.check()


def test_half_open_after_cooldown_then_closes_on_success():
    clock = FakeClock()
    breaker = CircuitBreaker("gemini", failure_threshold=1, cooldown_seconds=300, clock=clock)
    breaker.record_failure(RateLimited())

    clock.now += 301
    assert breaker.state == "half-open"
    breaker.check()  # one trial call is allowed
    breaker.record_success()
    assert breaker.state == "closed"


def test_failure_while_half_open_reopens_immediately():
    clock = FakeClock()
    breaker = CircuitBreaker("gemini", failure_threshold=3, cooldown_seconds=300, clock=clock)
    for _ in range(3):
        breaker.record_failure(RateLimited())

    clock.now += 301
    breaker.record_failure(RateLimited())  # the trial call failed
    assert breaker.state == "open"


def test_bad_requests_do_not_trip_the_breaker():
    breaker = CircuitBreaker("gemini", failure_threshold=1)
    breaker.record_failure(BadRequest())
    assert breaker.state == "closed"


# ---------- wired into a chat model + fallback ----------


class FlakyModel(GenericFakeChatModel):
    """Always rate-limited; counts how often the provider is actually called."""

    calls: int = 0

    def _generate(self, *args, **kwargs):
        self.calls += 1
        raise RateLimited("RESOURCE_EXHAUSTED")


class GuardedFlaky(CircuitBreakerMixin, FlakyModel):
    pass


async def test_open_circuit_skips_the_provider_and_fallback_answers():
    primary = GuardedFlaky(messages=iter([]))
    model = with_fallback(primary, replies("From Groq."))
    threshold = get_settings().breaker_failure_threshold

    for _ in range(threshold):
        assert (await model.ainvoke("hi")).text == "From Groq."
    assert primary.calls == threshold

    # Circuit is open: the provider isn't called at all any more.
    for _ in range(5):
        assert (await model.ainvoke("hi")).text == "From Groq."
    assert primary.calls == threshold


async def test_streaming_falls_back_when_circuit_is_open():
    primary = GuardedFlaky(messages=iter([]))
    model = with_fallback(primary, replies("Streamed from Groq."))
    for _ in range(get_settings().breaker_failure_threshold):
        await model.ainvoke("hi")

    text = "".join([chunk.text async for chunk in model.astream("hi")])
    assert text == "Streamed from Groq."


async def test_llm_primary_fallback_flips_the_order(monkeypatch):
    gemini, groq = replies("gemini"), replies("groq")

    monkeypatch.setattr(get_settings(), "llm_primary", "gemini")  # independent of local .env
    assert (await _ordered(gemini, groq).ainvoke("hi")).text == "gemini"
    monkeypatch.setattr(get_settings(), "llm_primary", "fallback")
    assert (await _ordered(gemini, groq).ainvoke("hi")).text == "groq"
    # Without a fallback configured, the setting can't apply.
    assert _ordered(gemini, None) is gemini
