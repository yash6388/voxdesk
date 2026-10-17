import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.api import businesses, chat, documents, health
from app.config import get_settings
from app.db.session import SessionLocal, engine
from app.graph.builder import build_graph
from app.rag.embeddings import get_embedder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: open the checkpointer's connection pool and compile the graph once.
    Shutdown: close pools cleanly."""
    settings = get_settings()
    async with AsyncConnectionPool(
        settings.psycopg_url,
        max_size=10,
        # Settings required by LangGraph's Postgres checkpointer.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()  # creates checkpoint tables if missing

        app.state.graph = build_graph(
            chat_llm=ChatGoogleGenerativeAI(
                model=settings.chat_model,
                google_api_key=settings.google_api_key,
                temperature=0.3,
                thinking_budget=0,  # no "thinking" pass: lower latency for chat/voice
            ),
            router_llm=ChatGoogleGenerativeAI(
                model=settings.router_model,
                google_api_key=settings.google_api_key,
                temperature=0,
                thinking_budget=0,
            ),
            embedder=get_embedder(),
            session_factory=SessionLocal,
            checkpointer=checkpointer,
        )
        yield
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
    app.include_router(chat.router)
    return app


app = create_app()
