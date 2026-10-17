from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings


@asynccontextmanager
async def postgres_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """LangGraph checkpointer backed by a psycopg connection pool. Used by the API's
    supervisor graph and by the booking agent (each under its own thread ids)."""
    async with AsyncConnectionPool(
        get_settings().psycopg_url,
        max_size=10,
        # Settings required by LangGraph's Postgres checkpointer.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()  # creates checkpoint tables if missing
        yield checkpointer
