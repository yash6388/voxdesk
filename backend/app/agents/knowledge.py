"""Knowledge Agent — an independent A2A service that answers questions about a business
from its own documents (hybrid RAG with citations).

    uv run python -m app.agents.knowledge      # http://127.0.0.1:8101

Input:  a standalone question (text) + business info in the request metadata.
Output: streamed "answer" text artifact, a "sources" data artifact, then COMPLETED.
"""

import logging
import uuid

import uvicorn
from a2a.helpers.proto_helpers import new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import a2a_pb2 as pb
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.a2a.server import TextStream, agent_card, create_a2a_app, emit_data, start_task
from app.config import get_settings
from app.errors import friendly_error
from app.rag.answer import answer_messages
from app.rag.embeddings import Embedder
from app.rag.retrieval import hybrid_search
from app.tracing import Turn, trace_turn

logger = logging.getLogger(__name__)


class KnowledgeAgentExecutor(AgentExecutor):
    def __init__(
        self, chat_llm: BaseChatModel, embedder: Embedder, session_factory: async_sessionmaker
    ):
        self._llm = chat_llm
        self._embedder = embedder
        self._sessions = session_factory

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task, updater = await start_task(context, event_queue)
        meta = context.metadata or {}
        question = context.get_user_input().strip()
        if not question or not meta.get("business_id"):
            await updater.reject(
                updater.new_agent_message(
                    [new_text_part("A question and business_id are required.")]
                )
            )
            return

        with trace_turn(
            "knowledge-agent",
            session_id=context.context_id,
            user_id=meta["business_id"],
            tags=["a2a", "knowledge"],
            input=question,
            parent=meta,  # continue the supervisor's trace
        ) as turn:
            await self._answer(question, meta, updater, turn)

    async def _answer(self, question: str, meta: dict, updater, turn: Turn) -> None:
        try:
            await updater.start_work()
            with turn.step("hybrid-search", as_type="retriever", input=question) as step:
                async with self._sessions() as session:
                    chunks = await hybrid_search(
                        session, self._embedder, uuid.UUID(meta["business_id"]), question
                    )
                if step is not None:
                    step.update(output=[{"chunk": c.chunk_index, "score": c.score} for c in chunks])
            await emit_data(
                updater,
                "sources",
                [
                    {
                        "filename": c.filename,
                        "chunk_index": c.chunk_index,
                        "content": c.content,
                        "score": c.score,
                    }
                    for c in chunks
                ],
            )

            answer = TextStream(updater)
            messages = answer_messages(
                question,
                chunks,
                meta.get("business_name", "the business"),
                meta.get("business_description", ""),
            )
            async for chunk in self._llm.astream(messages, config=turn.callbacks()):
                await answer.write(chunk.text)
            turn.output(answer.text)
            await updater.complete(updater.new_agent_message([new_text_part(answer.text)]))
        except Exception as exc:
            logger.exception("Knowledge agent failed")
            await updater.failed(updater.new_agent_message([new_text_part(friendly_error(exc))]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Answers are short-lived; cancellation isn't supported.")


def knowledge_card(url: str) -> pb.AgentCard:
    return agent_card(
        name="VoxDesk Knowledge Agent",
        description=(
            "Answers customer questions about a business from its own documents, with citations."
        ),
        url=url,
        skills=[
            pb.AgentSkill(
                id="answer_business_question",
                name="Answer business question",
                description=(
                    "Hybrid search (vector + full-text) over the business's knowledge base, then a "
                    "grounded answer citing sources like [1]. Says so when the answer isn't known. "
                    "Requires metadata: business_id, business_name."
                ),
                tags=["rag", "faq", "knowledge"],
                examples=["How much is a keratin treatment?", "Are you open on Sundays?"],
            )
        ],
    )


def create_app(executor: AgentExecutor | None = None):
    s = get_settings()
    if executor is None:
        from app.db.session import SessionLocal
        from app.llm import chat_llm
        from app.rag.embeddings import get_embedder

        executor = KnowledgeAgentExecutor(chat_llm(), get_embedder(), SessionLocal)
    return create_a2a_app(executor, knowledge_card(s.knowledge_agent_url), s.a2a_api_key)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    s = get_settings()
    uvicorn.run(create_app(), host=s.agents_host, port=s.knowledge_agent_port)
