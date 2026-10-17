import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DocumentStatus


class BusinessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    filename: str
    content_type: str
    status: DocumentStatus
    num_chunks: int
    error: str | None
    created_at: datetime


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    id: str
    content: str
    document_id: str
    filename: str
    chunk_index: int
    score: float
    semantic_rank: int | None
    keyword_rank: int | None


class ChatRequest(BaseModel):
    business_id: uuid.UUID
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(
        default=None, description="Omit to start a new conversation; reuse to continue one."
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatHistory(BaseModel):
    thread_id: str
    messages: list[ChatMessage]
