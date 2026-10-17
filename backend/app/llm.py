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

from app.config import get_settings


class FallbackChatModel(ChatOpenAI):
    """OpenAI-compatible APIs don't all support strict JSON-schema output; function
    calling is far more widely supported, so structured output uses that."""

    def with_structured_output(self, schema, *, method="function_calling", **kwargs) -> Runnable:
        # The return annotation matters: `with_fallbacks` only forwards methods that are
        # annotated as returning a Runnable.
        return super().with_structured_output(schema, method=method, **kwargs)


def with_fallback(primary: BaseChatModel, fallback: BaseChatModel | None) -> Runnable:
    return primary.with_fallbacks([fallback]) if fallback is not None else primary


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


def chat_llm() -> Runnable:
    """Model for customer-facing answers and the booking agent."""
    s = get_settings()
    primary = ChatGoogleGenerativeAI(
        model=s.chat_model,
        google_api_key=s.google_api_key,
        temperature=0.3,
        thinking_budget=0,  # no "thinking" pass: lower latency for chat/voice
        # Fail fast: a customer shouldn't wait ~35 s of silent backoff on a 429 —
        # especially now that a fallback model can answer instead.
        max_retries=2,
    )
    return with_fallback(primary, _fallback_model(0.3))


def router_llm() -> Runnable:
    """Small, fast model for intent classification and query rewriting."""
    s = get_settings()
    primary = ChatGoogleGenerativeAI(
        model=s.router_model,
        google_api_key=s.google_api_key,
        temperature=0,
        thinking_budget=0,
        max_retries=2,
    )
    return with_fallback(primary, _fallback_model(0))
