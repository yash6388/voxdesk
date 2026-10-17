from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings


def chat_llm() -> ChatGoogleGenerativeAI:
    """Model for customer-facing answers and the booking agent."""
    s = get_settings()
    return ChatGoogleGenerativeAI(
        model=s.chat_model,
        google_api_key=s.google_api_key,
        temperature=0.3,
        thinking_budget=0,  # no "thinking" pass: lower latency for chat/voice
        # Fail fast: a customer shouldn't wait ~35 s of silent backoff on a 429.
        max_retries=2,
    )


def router_llm() -> ChatGoogleGenerativeAI:
    """Small, fast model for intent classification and query rewriting."""
    s = get_settings()
    return ChatGoogleGenerativeAI(
        model=s.router_model,
        google_api_key=s.google_api_key,
        temperature=0,
        thinking_budget=0,
        max_retries=2,
    )
