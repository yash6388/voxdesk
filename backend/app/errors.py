def is_rate_limited(exc: BaseException | None) -> bool:
    """True if the LLM provider rejected the call for quota/rate limits (HTTP 429)."""
    while exc is not None:
        if getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def is_provider_outage(exc: BaseException | None) -> bool:
    """Errors that mean "the provider can't serve us right now" — rate limits, 5xx, timeouts —
    as opposed to bad requests, which are our bugs and shouldn't trip a circuit breaker."""
    if is_rate_limited(exc):
        return True
    while exc is not None:
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if isinstance(code, int) and code >= 500:
            return True
        if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def friendly_error(exc: BaseException) -> str:
    """A customer-safe message for an unexpected failure."""
    if is_rate_limited(exc):
        return "Our assistant is handling too many requests right now. Please try again shortly."
    return "Sorry, something went wrong on our side. Please try again."
