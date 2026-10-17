"""Circuit breaker for an LLM provider.

    CLOSED ──(N outages in a row)──► OPEN ──(cooldown passes)──► HALF-OPEN
      ▲                               │ calls fail instantly      │ one trial call
      └──────────── success ──────────┴──────── failure → OPEN ◄──┘

While OPEN, calls raise `CircuitOpenError` immediately, so `with_fallbacks` moves to the
backup model in ~0 ms instead of waiting for yet another 429 from a provider we already
know is out of quota.
"""

import contextvars
import logging
import time
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel

from app.config import get_settings
from app.errors import is_provider_outage

logger = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    """Raised instead of calling a provider whose circuit is open."""


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "open" if self._clock() - self._opened_at < self.cooldown_seconds else "half-open"

    def check(self) -> None:
        if self.state == "open":
            raise CircuitOpenError(f"{self.name}: circuit open, skipping provider")

    def record_success(self) -> None:
        if self._opened_at is not None:
            logger.info("Circuit for %s closed — provider is back", self.name)
        self._failures = 0
        self._opened_at = None

    def record_failure(self, exc: BaseException) -> None:
        if not is_provider_outage(exc):
            return  # our own bad request: not the provider's fault
        half_open = self.state == "half-open"
        self._failures += 1
        if half_open or self._failures >= self.failure_threshold:
            self._opened_at = self._clock()
            logger.warning(
                "Circuit for %s OPEN for %ss after %d failure(s)",
                self.name,
                self.cooldown_seconds,
                self._failures,
            )


# One breaker per provider+model per process, shared by every wrapper of that model
# (plain, tool-bound, structured-output) because they all draw on the same quota.
_breakers: dict[str, CircuitBreaker] = {}


def breaker_for(name: str, **kwargs) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, **kwargs)
    return _breakers[name]


# Set while a guarded call is in progress. LangChain's default async methods run the sync
# ones in a thread (with the context copied), so without this one failed call could be
# checked and counted twice — once in _agenerate and again in the _generate it delegates to.
_guarded = contextvars.ContextVar("circuit_breaker_guarded", default=False)


class CircuitBreakerMixin(BaseChatModel):
    """Mix into a chat model class to guard all four call paths with a breaker.
    `bind_tools()` / `with_structured_output()` wrap the same instance, so they're
    guarded too."""

    def _breaker(self) -> CircuitBreaker:
        s = get_settings()
        name = f"{type(self).__name__}:{getattr(self, 'model', '')}"
        return breaker_for(
            name,
            failure_threshold=s.breaker_failure_threshold,
            cooldown_seconds=s.breaker_cooldown_seconds,
        )

    def _generate(self, *args, **kwargs):
        if _guarded.get():
            return super()._generate(*args, **kwargs)
        breaker = self._breaker()
        breaker.check()
        token = _guarded.set(True)
        try:
            result = super()._generate(*args, **kwargs)
        except Exception as exc:
            breaker.record_failure(exc)
            raise
        finally:
            _guarded.reset(token)
        breaker.record_success()
        return result

    async def _agenerate(self, *args, **kwargs):
        if _guarded.get():
            return await super()._agenerate(*args, **kwargs)
        breaker = self._breaker()
        breaker.check()
        token = _guarded.set(True)
        try:
            result = await super()._agenerate(*args, **kwargs)
        except Exception as exc:
            breaker.record_failure(exc)
            raise
        finally:
            _guarded.reset(token)
        breaker.record_success()
        return result

    def _stream(self, *args, **kwargs):
        if _guarded.get():
            yield from super()._stream(*args, **kwargs)
            return
        breaker = self._breaker()
        breaker.check()
        _guarded.set(True)
        try:
            yield from super()._stream(*args, **kwargs)
        except Exception as exc:
            breaker.record_failure(exc)
            raise
        finally:
            # Generators can be closed from another context (e.g. an abandoned stream);
            # set() is safe there, unlike reset(token).
            _guarded.set(False)
        breaker.record_success()

    async def _astream(self, *args, **kwargs):
        if _guarded.get():
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk
            return
        breaker = self._breaker()
        breaker.check()
        _guarded.set(True)
        try:
            async for chunk in super()._astream(*args, **kwargs):
                yield chunk
        except Exception as exc:
            breaker.record_failure(exc)
            raise
        finally:
            # Generators can be closed from another context (e.g. an abandoned stream);
            # set() is safe there, unlike reset(token).
            _guarded.set(False)
        breaker.record_success()
