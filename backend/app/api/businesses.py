import re
import secrets
import uuid
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import EmbedderDep, SessionDep
from app.auth import CurrentUser, OwnedBusiness
from app.db.models import Business
from app.rag.retrieval import hybrid_search
from app.schemas import BusinessCreate, BusinessOut, PublicBusiness, SearchRequest, SearchResult

router = APIRouter(prefix="/businesses", tags=["businesses"])
public_router = APIRouter(prefix="/public", tags=["public"])


async def get_business_or_404(business_id: uuid.UUID, session: AsyncSession) -> Business:
    """Lookup without an ownership check — for customer-facing endpoints (chat, voice)."""
    business = await session.get(Business, business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return business


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "business"


async def unique_slug(session: AsyncSession, name: str) -> str:
    """`glow-studio` if free, else `glow-studio-3fa1` (random suffix, never serial/guessable)."""
    base = slugify(name)
    slug = base
    while await session.scalar(select(Business.id).where(Business.slug == slug)):
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


@router.post("", response_model=BusinessOut, status_code=status.HTTP_201_CREATED)
async def create_business(body: BusinessCreate, user: CurrentUser, session: SessionDep):
    business = Business(
        **body.model_dump(), owner_id=user.id, slug=await unique_slug(session, body.name)
    )
    session.add(business)
    await session.commit()
    return business


@router.get("", response_model=list[BusinessOut])
async def list_businesses(user: CurrentUser, session: SessionDep):
    """Only the signed-in owner's businesses."""
    result = await session.scalars(
        select(Business).where(Business.owner_id == user.id).order_by(Business.created_at.desc())
    )
    return result.all()


@router.get("/{business_id}", response_model=BusinessOut)
async def get_business(business: OwnedBusiness):
    return business


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_business(business: OwnedBusiness, session: SessionDep):
    await session.delete(business)
    await session.commit()


@router.post("/{business_id}/search", response_model=list[SearchResult])
async def search(
    business: OwnedBusiness,
    body: SearchRequest,
    session: SessionDep,
    embedder: EmbedderDep,
):
    """Debug view of hybrid retrieval: shows each chunk's semantic and keyword rank."""
    chunks = await hybrid_search(session, embedder, business.id, body.query, body.top_k)
    return [asdict(c) for c in chunks]


@public_router.get("/businesses/{slug}", response_model=PublicBusiness)
async def public_business(slug: str, session: SessionDep):
    """What the anonymous customer chat page needs: no owner, settings or private data."""
    business = await session.scalar(select(Business).where(Business.slug == slug))
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return business
