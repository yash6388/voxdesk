import enum
import uuid
from datetime import datetime, time

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Business(TimestampMixin, Base):
    """A tenant: every document, chunk and conversation belongs to one business."""

    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # IANA name, e.g. "Asia/Kolkata". Bookings are stored in UTC and shown in this zone.
    timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Kolkata", server_default="Asia/Kolkata"
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")

    documents: Mapped[list["Document"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )


class DocumentStatus(enum.StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(TimestampMixin, Base):
    """An uploaded file. Ingestion runs in the background and updates `status`."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(
            DocumentStatus,
            name="document_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DocumentStatus.PROCESSING,
    )
    num_chunks: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Chunk(TimestampMixin, Base):
    """A piece of a document, stored with both a vector (semantic search)
    and a tsvector (keyword search) so hybrid retrieval is one SQL query."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Denormalized from document so retrieval filters by tenant without a join.
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    # Postgres keeps this in sync with `content` automatically.
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )


class Service(TimestampMixin, Base):
    """Something a customer can book, e.g. "Women's haircut — 60 min — ₹1,200"."""

    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price: Mapped[int | None] = mapped_column(Integer)  # whole currency units
    # Services are deactivated rather than deleted so past bookings keep their service.
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (CheckConstraint("duration_minutes > 0", name="ck_services_duration"),)


class BusinessHours(Base):
    """Opening hours for one weekday. A missing weekday means closed."""

    __tablename__ = "business_hours"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday … 6 = Sunday
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)

    __table_args__ = (
        UniqueConstraint("business_id", "weekday", name="uq_business_hours_weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_business_hours_weekday"),
        CheckConstraint("opens_at < closes_at", name="ck_business_hours_order"),
    )


class BookingStatus(enum.StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_phone: Mapped[str] = mapped_column(String(32), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(
        Enum(
            BookingStatus,
            name="booking_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=BookingStatus.CONFIRMED,
    )

    service: Mapped[Service] = relationship()

    __table_args__ = (
        CheckConstraint("start_at < end_at", name="ck_bookings_time_order"),
        # The database itself refuses overlapping confirmed bookings for the same business,
        # so two simultaneous requests can never double-book a slot (needs btree_gist).
        ExcludeConstraint(
            ("business_id", "="),
            (text("tstzrange(start_at, end_at, '[)')"), "&&"),
            name="ex_bookings_no_overlap",
            using="gist",
            where=text("status = 'confirmed'"),
        ),
    )
