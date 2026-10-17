def is_rate_limited(exc: BaseException | None) -> bool:
    """True if the LLM provider rejected the call for quota/rate limits (HTTP 429)."""
    while exc is not None:
        if getattr(exc, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(exc):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def friendly_error(exc: BaseException) -> str:
    """A customer-safe message for an unexpected failure."""
    if is_rate_limited(exc):
        return "Our assistant is handling too many requests right now. Please try again shortly."
    return "Sorry, something went wrong on our side. Please try again."
