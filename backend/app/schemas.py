import uuid
from datetime import datetime, time
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.db.models import BookingStatus, ConversationStatus, DocumentStatus


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str


class AuthResponse(BaseModel):
    user: UserOut
    # Also set as an httpOnly cookie; returned for API clients (e.g. Swagger "Authorize").
    access_token: str
    token_type: str = "bearer"


class PublicBusiness(BaseModel):
    """What an anonymous customer may see about a business."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str


class BusinessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    timezone: str = "Asia/Kolkata"
    currency: str = Field(default="INR", min_length=3, max_length=3)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, v: str) -> str:
        if v not in available_timezones():
            raise ValueError("Unknown timezone")
        return v


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str
    timezone: str
    currency: str
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


class ChatResume(BaseModel):
    business_id: uuid.UUID
    thread_id: str
    approved: bool


class ChatHistory(BaseModel):
    thread_id: str
    messages: list[ChatMessage]
    pending_confirmation: dict | None = None


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    duration_minutes: int = Field(ge=5, le=480)
    price: int | None = Field(default=None, ge=0)


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    duration_minutes: int
    price: int | None
    active: bool


class HoursDay(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    weekday: int = Field(ge=0, le=6, description="0 = Monday … 6 = Sunday")
    opens_at: time
    closes_at: time

    @model_validator(mode="after")
    def opens_before_closes(self):
        if self.opens_at >= self.closes_at:
            raise ValueError("opens_at must be before closes_at")
        return self


class HoursUpdate(BaseModel):
    days: list[HoursDay] = Field(description="Days not listed are closed.")

    @field_validator("days")
    @classmethod
    def unique_weekdays(cls, v: list[HoursDay]) -> list[HoursDay]:
        if len({d.weekday for d in v}) != len(v):
            raise ValueError("Each weekday may appear only once")
        return v


class BookingOut(BaseModel):
    id: uuid.UUID
    service_name: str
    customer_name: str
    customer_phone: str
    start_at: datetime
    end_at: datetime
    status: BookingStatus
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: str
    channel: str
    status: ConversationStatus
    handoff_reason: str | None
    turn_count: int
    created_at: datetime
    last_activity_at: datetime
    last_message: str | None = None


class ConversationDetail(ConversationOut):
    messages: list[ChatMessage]


class DailyPoint(BaseModel):
    date: str
    turns: int
    conversations: int


class AnalyticsOut(BaseModel):
    days: int
    conversations: int
    turns: int
    bookings: int
    handoffs: int
    guardrail_blocks: int
    errors: int
    needs_human_open: int
    outcomes: dict[str, int]
    intents: dict[str, int]
    channels: dict[str, int]
    daily: list[DailyPoint]
    first_token_p50_ms: int | None
    first_token_p95_ms: int | None
