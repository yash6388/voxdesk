"""LLM-as-judge for faithfulness: is every claim in the answer supported by the context?"""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

JUDGE_PROMPT = """You grade a customer-service assistant's answer for FAITHFULNESS.

Faithful = every factual claim in the answer (prices, times, policies, names, numbers) is
directly supported by the CONTEXT. Politeness, greetings and offers to help are not claims.
Citation markers like [1] can be ignored. Do not use outside knowledge.

Score 1-5:
5 = every claim supported · 4 = supported with trivial rewording/rounding ·
3 = one minor unsupported detail · 2 = an important unsupported claim · 1 = mostly unsupported"""


class Judgement(BaseModel):
    unsupported_claims: list[str] = Field(
        description="Claims in the answer NOT supported by the context (empty if none)."
    )
    score: int = Field(ge=1, le=5, description="Faithfulness score, 1-5.")
    reasoning: str = Field(description="One or two sentences explaining the score.")


async def judge_faithfulness(judge_llm, question: str, context: str, answer: str) -> Judgement:
    structured = judge_llm.with_structured_output(Judgement)
    return await structured.ainvoke(
        [
            SystemMessage(JUDGE_PROMPT),
            HumanMessage(f"QUESTION:\n{question}\n\nCONTEXT:\n{context}\n\nANSWER:\n{answer}"),
        ]
    )
