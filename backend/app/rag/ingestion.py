import io
import logging
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.db.models import Chunk, Document, DocumentStatus
from app.rag.embeddings import Embedder

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/markdown": "text",
}


def extract_text(data: bytes, content_type: str) -> str:
    if SUPPORTED_TYPES.get(content_type) == "pdf":
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    return data.decode("utf-8", errors="replace")


def split_text(text: str) -> list[str]:
    s = get_settings()
    # Tries to split on paragraphs first, then lines, then sentences, so chunks
    # stay semantically coherent; overlap keeps context across chunk boundaries.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=s.chunk_size, chunk_overlap=s.chunk_overlap
    )
    return [c for c in splitter.split_text(text) if c.strip()]


async def ingest_document(
    document_id: uuid.UUID,
    data: bytes,
    session_factory: async_sessionmaker,
    embedder: Embedder,
) -> None:
    """Parse → chunk → embed → store. Runs as a background task after upload."""
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return
        try:
            # PDF parsing is CPU-bound; keep it off the event loop.
            text = await run_in_threadpool(extract_text, data, document.content_type)
            pieces = split_text(text)
            if not pieces:
                raise ValueError("No extractable text found in document")

            vectors = await embedder.embed_documents(pieces)
            session.add_all(
                Chunk(
                    business_id=document.business_id,
                    document_id=document.id,
                    chunk_index=i,
                    content=content,
                    embedding=vector,
                )
                for i, (content, vector) in enumerate(zip(pieces, vectors, strict=True))
            )
            document.num_chunks = len(pieces)
            document.status = DocumentStatus.READY
        except Exception as exc:
            logger.exception("Ingestion failed for document %s", document_id)
            await session.rollback()
            document = await session.get(Document, document_id)
            document.status = DocumentStatus.FAILED
            document.error = str(exc)[:1000]
        await session.commit()
