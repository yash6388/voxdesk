import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.a2a.client import A2AAgent
from app.api import booking, businesses, chat, documents, health, voice
from app.config import get_settings
from app.db.session import engine
from app.graph.checkpoint import postgres_checkpointer
from app.graph.supervisor import build_supervisor
from app.llm import chat_llm, router_llm
from app.voice.providers import warm_up_voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: open the checkpointer pool, connect to the A2A agents, compile the
    supervisor graph once. Shutdown: close everything cleanly."""
    settings = get_settings()
    knowledge = A2AAgent("knowledge", settings.knowledge_agent_url, settings.a2a_api_key)
    booking_agent = A2AAgent("booking", settings.booking_agent_url, settings.a2a_api_key)
    # Speech models load in the background; the API is usable immediately.
    warmup = asyncio.create_task(warm_up_voice())
    async with postgres_checkpointer() as checkpointer:
        app.state.graph = build_supervisor(
            router_llm=router_llm(),
            chat_llm=chat_llm(),
            knowledge_agent=knowledge,
            booking_agent=booking_agent,
            checkpointer=checkpointer,
        )
        yield
    warmup.cancel()
    await knowledge.aclose()
    await booking_agent.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(businesses.router)
    app.include_router(documents.router)
    app.include_router(booking.router)
    app.include_router(chat.router)
    app.include_router(voice.router)
    return app


app = create_app()
