"""Langfuse tracing (works with Langfuse Cloud or a self-hosted instance).

- Each conversation turn (chat or voice) is one trace, grouped by session = conversation,
  user = business, tags = channel.
- LLM calls, tool calls and graph nodes are captured by Langfuse's LangChain callback
  handler — including which model answered (Gemini or the fallback), tokens and latency.
- Distributed across A2A: the supervisor sends its trace id in the message metadata and
  the agents continue that same trace, so one turn = one trace across processes.

Everything is a no-op when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY aren't set.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# Keys used in A2A message metadata to continue a trace in another process.
TRACE_ID_KEY = "langfuse_trace_id"
PARENT_SPAN_KEY = "langfuse_parent_span_id"


@lru_cache
def get_langfuse():
    s = get_settings()
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=s.langfuse_public_key,
        secret_key=s.langfuse_secret_key,
        host=s.langfuse_host,
        environment=s.environment,
    )


@dataclass
class Turn:
    """Handle for the current turn's trace (or a no-op when tracing is off)."""

    span: Any = None
    handler: Any = None  # LangChain callback handler → pass in the graph/LLM config
    trace_url: str | None = None

    def callbacks(self, config: dict | None = None) -> dict:
        config = dict(config or {})
        if self.handler is not None:
            config["callbacks"] = [*config.get("callbacks", []), self.handler]
        return config

    def input(self, value: Any) -> None:
        if self.span is not None:
            self.span.update(input=value)

    def output(self, value: Any) -> None:
        if self.span is not None:
            self.span.update(output=value)

    @contextmanager
    def step(self, name: str, *, as_type: str = "span", input: Any = None) -> Iterator[Any]:
        """A child observation, e.g. speech-to-text or a retrieval."""
        langfuse = get_langfuse()
        if langfuse is None or self.span is None:
            yield None
            return
        with langfuse.start_as_current_observation(name=name, as_type=as_type, input=input) as obs:
            yield obs


def parent_context(metadata: dict | None) -> dict | None:
    """Langfuse trace context from A2A metadata, so a remote agent continues the caller's
    trace instead of starting a new one."""
    if not metadata or not metadata.get(TRACE_ID_KEY):
        return None
    context = {"trace_id": metadata[TRACE_ID_KEY]}
    if metadata.get(PARENT_SPAN_KEY):
        context["parent_span_id"] = metadata[PARENT_SPAN_KEY]
    return context


@contextmanager
def trace_turn(
    name: str,
    *,
    session_id: str,
    user_id: str,
    tags: list[str],
    input: Any = None,
    parent: dict | None = None,
) -> Iterator[Turn]:
    """Open (or, with `parent`, continue) a trace for one turn."""
    langfuse = get_langfuse()
    if langfuse is None:
        yield Turn()
        return

    from langfuse import propagate_attributes
    from langfuse.langchain import CallbackHandler

    with (
        langfuse.start_as_current_observation(
            name=name, as_type="agent", input=input, trace_context=parent_context(parent)
        ) as span,
        propagate_attributes(session_id=session_id, user_id=user_id, tags=tags),
    ):
        trace_url = langfuse.get_trace_url(trace_id=langfuse.get_current_trace_id())
        yield Turn(span=span, handler=CallbackHandler(), trace_url=trace_url)


def trace_metadata() -> dict:
    """The current trace's ids, to send along to an A2A agent."""
    langfuse = get_langfuse()
    if langfuse is None:
        return {}
    trace_id = langfuse.get_current_trace_id()
    if not trace_id:
        return {}
    meta = {TRACE_ID_KEY: trace_id}
    if span_id := langfuse.get_current_observation_id():
        meta[PARENT_SPAN_KEY] = span_id
    return meta


def flush() -> None:
    """Send buffered traces before the process exits."""
    langfuse = get_langfuse()
    if langfuse is not None:
        try:
            langfuse.flush()
        except Exception:
            logger.warning("Langfuse flush failed", exc_info=True)
