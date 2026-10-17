"""Create (or update) the "Glow Studio Salon" demo business: services, opening hours,
and the sample knowledge-base document. Safe to run repeatedly.

    uv run python -m scripts.seed_demo
"""

import asyncio
from datetime import time
from pathlib import Path

from sqlalchemy import select

from app.api.businesses import unique_slug
from app.booking.service import set_hours
from app.db.models import Business, Document, Service, User
from app.db.session import SessionLocal, engine
from app.rag.embeddings import get_embedder
from app.rag.ingestion import ingest_document

NAME = "Glow Studio Salon"
DOC = Path(__file__).resolve().parents[2] / "samples" / "glow-studio-salon.md"

SERVICES = [  # (name, minutes, price ₹)
    ("Women's haircut & blow-dry", 60, 1200),
    ("Men's haircut", 30, 500),
    ("Kids' haircut", 30, 400),
    ("Global hair colour", 120, 3500),
    ("Keratin smoothing treatment", 180, 6500),
    ("Hair spa", 45, 1500),
    ("Classic facial", 60, 1800),
    ("Manicure", 40, 700),
    ("Pedicure", 50, 900),
]

# Mirrors the opening hours in the sample document. Monday (0) is closed.
HOURS = [
    (1, time(10), time(20)),
    (2, time(10), time(20)),
    (3, time(10), time(20)),
    (4, time(10), time(20)),
    (5, time(9), time(21)),
    (6, time(10), time(18)),
]


async def main() -> None:
    async with SessionLocal() as session:
        business = await session.scalar(select(Business).where(Business.name == NAME))
        # Owned by the first account if one exists; otherwise the first signup claims it.
        owner = await session.scalar(select(User).order_by(User.created_at))
        if business is None:
            business = Business(
                name=NAME,
                description="A hair and beauty salon in Koregaon Park, Pune.",
                slug=await unique_slug(session, NAME),
                owner_id=owner.id if owner else None,
            )
            session.add(business)
            await session.commit()
            print(f"Created business {business.id}")
        else:
            print(f"Using existing business {business.id}")

        existing = set(
            await session.scalars(select(Service.name).where(Service.business_id == business.id))
        )
        new = [
            Service(business_id=business.id, name=n, duration_minutes=m, price=p)
            for n, m, p in SERVICES
            if n not in existing
        ]
        session.add_all(new)
        await session.commit()
        print(f"Services: {len(new)} added, {len(existing)} already present")

        await set_hours(session, business.id, HOURS)
        print("Opening hours set (Tue–Sun)")

        has_doc = await session.scalar(
            select(Document.id).where(Document.business_id == business.id)
        )
        if has_doc is None:
            document = Document(
                business_id=business.id, filename=DOC.name, content_type="text/markdown"
            )
            session.add(document)
            await session.commit()
            await ingest_document(document.id, DOC.read_bytes(), SessionLocal, get_embedder())
            print("Sample document ingested")
        else:
            print("Knowledge base already has documents")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
