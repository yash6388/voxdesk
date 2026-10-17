"""A throwaway business for evaluation runs: created from the sample documents, deleted after."""

import secrets
from contextlib import asynccontextmanager
from datetime import time
from pathlib import Path

from sqlalchemy import select

from app.booking.service import set_hours
from app.config import get_settings
from app.db.models import Business, Document, Service
from app.db.session import SessionLocal
from app.rag.embeddings import Embedder
from app.rag.ingestion import ingest_document

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
SERVICES = [("Men's haircut", 30, 500), ("Manicure", 40, 700), ("Classic facial", 60, 1800)]
HOURS = [(d, time(10), time(18)) for d in range(1, 7)]  # Tue–Sun, Monday closed


@asynccontextmanager
async def eval_business(documents: list[str], embedder: Embedder, chunk_size: int | None = None):
    """Yield a fresh business with the given documents ingested; always deleted afterwards
    (cascades to documents, chunks, services and hours)."""
    settings = get_settings()
    original = settings.chunk_size, settings.chunk_overlap
    async with SessionLocal() as session:
        business = Business(
            name="Glow Studio Salon",
            description="A hair and beauty salon in Koregaon Park, Pune.",
            slug=f"eval-{secrets.token_hex(4)}",
        )
        session.add(business)
        await session.flush()
        session.add_all(
            Service(business_id=business.id, name=n, duration_minutes=m, price=p)
            for n, m, p in SERVICES
        )
        docs = [
            Document(business_id=business.id, filename=name, content_type="text/markdown")
            for name in documents
        ]
        session.add_all(docs)
        await session.commit()
        await set_hours(session, business.id, HOURS)

    try:
        if chunk_size:
            settings.chunk_size = chunk_size
            settings.chunk_overlap = min(original[1], chunk_size // 5)
        for doc in docs:
            await ingest_document(
                doc.id, (SAMPLES / doc.filename).read_bytes(), SessionLocal, embedder
            )
        settings.chunk_size, settings.chunk_overlap = original
        async with SessionLocal() as session:
            services = list(
                await session.scalars(select(Service).where(Service.business_id == business.id))
            )
        yield business, services
    finally:
        settings.chunk_size, settings.chunk_overlap = original
        async with SessionLocal() as session:
            await session.delete(await session.get(Business, business.id))
            await session.commit()
