from sqlalchemy import select

from app.config import get_settings
from app.db.models import Business, Document, DocumentStatus
from app.db.session import SessionLocal
from app.rag.ingestion import ingest_document, split_text
from app.rag.retrieval import hybrid_search

SALON_DOC = """
# Opening hours
We are open Tuesday to Sunday from 10 AM to 8 PM. We are closed on Mondays.

# Parking
Free basement parking is available for six cars.

# Cancellation policy
Cancel up to 24 hours before your appointment for free. Late cancellations cost 50%.
""".strip()


async def create_business_with_doc(name: str, content: str, embedder) -> Business:
    async with SessionLocal() as session:
        business = Business(name=name)
        session.add(business)
        await session.flush()
        document = Document(business_id=business.id, filename="info.md", content_type="text/plain")
        session.add(document)
        await session.commit()

    await ingest_document(document.id, content.encode(), SessionLocal, embedder)
    return business


async def get_only_document(business: Business) -> Document:
    async with SessionLocal() as session:
        return await session.scalar(select(Document).where(Document.business_id == business.id))


def test_split_text_respects_chunk_size():
    chunks = split_text("word " * 2000)
    assert len(chunks) > 1
    assert all(len(c) <= get_settings().chunk_size for c in chunks)


async def test_ingest_marks_document_ready(db, fake_embedder):
    business = await create_business_with_doc("Salon", SALON_DOC * 10, fake_embedder)

    document = await get_only_document(business)
    assert document.status == DocumentStatus.READY
    assert document.num_chunks > 1


async def test_ingest_empty_document_fails_gracefully(db, fake_embedder):
    business = await create_business_with_doc("Empty", "   ", fake_embedder)

    document = await get_only_document(business)
    assert document.status == DocumentStatus.FAILED
    assert "No extractable text" in document.error


async def test_hybrid_search_finds_relevant_chunk(db, fake_embedder, monkeypatch):
    # Small chunks so each section of the doc becomes its own chunk.
    monkeypatch.setattr(get_settings(), "chunk_size", 120)
    monkeypatch.setattr(get_settings(), "chunk_overlap", 0)
    business = await create_business_with_doc("Salon", SALON_DOC, fake_embedder)

    async with SessionLocal() as session:
        results = await hybrid_search(session, fake_embedder, business.id, "is there parking?")

    assert "parking" in results[0].content.lower()
    assert results[0].keyword_rank == 1


async def test_hybrid_search_is_isolated_per_business(db, fake_embedder):
    salon = await create_business_with_doc("Salon", SALON_DOC, fake_embedder)
    await create_business_with_doc("Clinic", "Dental cleaning costs 2000 rupees.", fake_embedder)

    async with SessionLocal() as session:
        results = await hybrid_search(session, fake_embedder, salon.id, "dental cleaning cost")

    assert all("dental" not in r.content.lower() for r in results)
