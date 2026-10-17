from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import tool

from app.config import Settings
from app.graph.state import Route
from app.llm import FallbackChatModel, with_fallback
from tests.fakes import FakeToolLLM, replies


class RateLimited(Exception):
    code = 429


class AlwaysFails(GenericFakeChatModel):
    """Stands in for Gemini on a bad day."""

    def _generate(self, *args, **kwargs):
        raise RateLimited("RESOURCE_EXHAUSTED")

    def bind_tools(self, tools, **kwargs) -> Runnable:
        return self


async def test_fallback_answers_when_primary_is_rate_limited():
    model = with_fallback(AlwaysFails(messages=iter([])), replies("From the backup model."))
    reply = await model.ainvoke("hi")
    assert reply.text == "From the backup model."


async def test_tool_binding_reaches_the_fallback_model():
    @tool
    def check_availability(date: str) -> str:
        """Free times."""
        return "15:00"

    backup = FakeToolLLM(
        messages=iter(
            [
                AIMessage(
                    "",
                    tool_calls=[{"name": "check_availability", "args": {"date": "x"}, "id": "1"}],
                )
            ]
        )
    )
    model = with_fallback(AlwaysFails(messages=iter([])), backup).bind_tools([check_availability])

    reply = await model.ainvoke("any slots?")
    assert reply.tool_calls[0]["name"] == "check_availability"


def test_no_fallback_without_a_token():
    primary = replies("x")
    assert with_fallback(primary, None) is primary


def test_fallback_key_accepts_common_variable_names(monkeypatch):
    names = ("FALLBACK_API_KEY", "HF_TOKEN", "HUGGINGFACE_API_KEY", "HUGGINGFACEHUB_API_TOKEN")
    for name in names:
        for other in names:
            monkeypatch.delenv(other, raising=False)
        monkeypatch.setenv(name, "key_test")
        assert Settings(_env_file=None).fallback_api_key == "key_test"


def test_fallback_uses_function_calling_for_structured_output():
    model = FallbackChatModel(model="m", base_url="http://x", api_key="k")
    # Building the structured runnable must not require strict JSON-schema support.
    structured = model.with_structured_output(Route)
    assert structured is not None
