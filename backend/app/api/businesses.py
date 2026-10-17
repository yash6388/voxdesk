import uuid
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import EmbedderDep, SessionDep
from app.db.models import Business
from app.rag.retrieval import hybrid_search
from app.schemas import BusinessCreate, BusinessOut, SearchRequest, SearchResult

router = APIRouter(prefix="/businesses", tags=["businesses"])


async def get_business_or_404(business_id: uuid.UUID, session: AsyncSession) -> Business:
    business = await session.get(Business, business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return business


@router.post("", response_model=BusinessOut, status_code=status.HTTP_201_CREATED)
async def create_business(body: BusinessCreate, session: SessionDep):
    business = Business(**body.model_dump())
    session.add(business)
    await session.commit()
    return business


@router.get("", response_model=list[BusinessOut])
async def list_businesses(session: SessionDep):
    result = await session.scalars(select(Business).order_by(Business.created_at.desc()))
    return result.all()


@router.get("/{business_id}", response_model=BusinessOut)
async def get_business(business_id: uuid.UUID, session: SessionDep):
    return await get_business_or_404(business_id, session)


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_business(business_id: uuid.UUID, session: SessionDep):
    business = await get_business_or_404(business_id, session)
    await session.delete(business)
    await session.commit()


@router.post("/{business_id}/search", response_model=list[SearchResult])
async def search(
    business_id: uuid.UUID,
    body: SearchRequest,
    session: SessionDep,
    embedder: EmbedderDep,
):
    """Debug view of hybrid retrieval: shows each chunk's semantic and keyword rank."""
    await get_business_or_404(business_id, session)
    chunks = await hybrid_search(session, embedder, business_id, body.query, body.top_k)
    return [asdict(c) for c in chunks]
