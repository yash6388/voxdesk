"""Building the grounded-answer prompt. Shared by the knowledge agent and the evaluation
suite, so evals measure exactly what production does."""

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.graph.prompts import RESPOND_PROMPT
from app.rag.retrieval import RetrievedChunk


def format_context(chunks: list[RetrievedChunk]) -> str:
    return (
        "\n\n".join(
            f"[{i}] (from {c.filename})\n{c.content}" for i, c in enumerate(chunks, start=1)
        )
        or "(no context retrieved)"
    )


def answer_messages(
    question: str,
    chunks: list[RetrievedChunk],
    business_name: str,
    business_description: str = "",
) -> list[BaseMessage]:
    system = RESPOND_PROMPT.format(
        business_name=business_name,
        business_description=business_description,
        context=format_context(chunks),
    )
    return [SystemMessage(system), HumanMessage(question)]
