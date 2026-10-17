"""Reusable FastAPI dependencies, declared once with Annotated so endpoints
just write `session: SessionDep` instead of repeating `Depends(...)`."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.rag.embeddings import Embedder, get_embedder

SessionDep = Annotated[AsyncSession, Depends(get_session)]
EmbedderDep = Annotated[Embedder, Depends(get_embedder)]
