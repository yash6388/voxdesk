import hashlib
import math
import os
import re

# Point the app at a separate test database BEFORE any app module is imported
# (settings and the engine are created at import time).
TEST_DATABASE_URL = os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://voxdesk:voxdesk@localhost:5433/voxdesk_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import engine  # noqa: E402

DIM = get_settings().embedding_dim


class FakeEmbedder:
    """Deterministic bag-of-words embedding: texts sharing words get similar vectors.
    Good enough to exercise retrieval without calling Gemini."""

    def _vec(self, text_: str) -> list[float]:
        v = [0.0] * DIM
        for word in re.findall(r"[a-z0-9]+", text_.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text_: str) -> list[float]:
        return self._vec(text_)


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture(scope="session")
async def _schema():
    """Create the test database and tables once per test run."""
    db_name = TEST_DATABASE_URL.rsplit("/", 1)[1]
    admin_dsn = TEST_DATABASE_URL.replace("+asyncpg", "").rsplit("/", 1)[0] + "/postgres"
    conn = await asyncpg.connect(admin_dsn)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name):
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()

    async with engine.begin() as c:
        await c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture
async def db(_schema):
    """Empty tables before each test that touches the database."""
    async with engine.begin() as c:
        await c.execute(text("TRUNCATE businesses, documents, chunks CASCADE"))
    yield
