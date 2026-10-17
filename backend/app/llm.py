"""Chat models, with automatic fallback to a second provider.

Primary: Gemini. Fallback: any OpenAI-compatible provider (Groq, OpenRouter, Hugging Face
router…), used only when the primary call fails — e.g. a free-tier 429.
`with_fallbacks` also forwards `bind_tools()` and `with_structured_output()` to both
models, so the router and the booking agent's tool calling are covered too.

Embeddings have no fallback on purpose: vectors from a different model live in a
different space and can't be compared with the stored ones.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.circuit_breaker import CircuitBreakerMixin
from app.config import get_settings


class GuardedGemini(CircuitBreakerMixin, ChatGoogleGenerativeAI):
    """Gemini behind a circuit breaker: once it's clearly out of quota, calls fail
    instantly so the fallback answers without waiting for another 429."""


class FallbackChatModel(ChatOpenAI):
    """OpenAI-compatible APIs don't all support strict JSON-schema output; function
    calling is far more widely supported, so structured output uses that."""

    def with_structured_output(self, schema, *, method="function_calling", **kwargs) -> Runnable:
        # The return annotation matters: `with_fallbacks` only forwards methods that are
        # annotated as returning a Runnable.
        return super().with_structured_output(schema, method=method, **kwargs)


def with_fallback(primary: BaseChatModel, fallback: BaseChatModel | None) -> Runnable:
    return primary.with_fallbacks([fallback]) if fallback is not None else primary


def _ordered(gemini: BaseChatModel, fallback: BaseChatModel | None) -> Runnable:
    """LLM_PRIMARY=fallback flips the order: the fallback provider answers first and
    Gemini becomes the backup."""
    if fallback is not None and get_settings().llm_primary == "fallback":
        return with_fallback(fallback, gemini)
    return with_fallback(gemini, fallback)


def _fallback_model(temperature: float) -> BaseChatModel | None:
    s = get_settings()
    if not s.fallback_api_key:
        return None
    return FallbackChatModel(
        model=s.fallback_model,
        base_url=s.fallback_base_url,
        api_key=s.fallback_api_key,
        temperature=temperature,
        max_retries=1,
        timeout=60,
    )


def _primary_retries(fallback: BaseChatModel | None) -> int:
    """With a fallback, fail over immediately instead of retrying (measured: a 429 fails
    in ~0.5 s with 0 retries vs ~2.3 s with 2). Without one, a couple of retries help."""
    return 0 if fallback is not None else 2


def chat_llm() -> Runnable:
    """Model for customer-facing answers and the booking agent."""
    s = get_settings()
    fallback = _fallback_model(0.3)
    primary = GuardedGemini(
        model=s.chat_model,
        google_api_key=s.google_api_key,
        temperature=0.3,
        thinking_budget=0,  # no "thinking" pass: lower latency for chat/voice
        max_retries=_primary_retries(fallback),
    )
    return _ordered(primary, fallback)


def router_llm() -> Runnable:
    """Small, fast model for intent classification and query rewriting."""
    s = get_settings()
    fallback = _fallback_model(0)
    primary = GuardedGemini(
        model=s.router_model,
        google_api_key=s.google_api_key,
        temperature=0,
        thinking_budget=0,
        max_retries=_primary_retries(fallback),
    )
    return _ordered(primary, fallback)
