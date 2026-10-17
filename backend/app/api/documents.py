import mimetypes
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.businesses import get_business_or_404
from app.api.deps import EmbedderDep, SessionDep
from app.config import get_settings
from app.db.models import Document
from app.db.session import SessionLocal
from app.rag.ingestion import SUPPORTED_TYPES, ingest_document
from app.schemas import DocumentOut

router = APIRouter(prefix="/businesses/{business_id}/documents", tags=["documents"])

mimetypes.add_type("text/markdown", ".md")


def resolve_content_type(file: UploadFile) -> str:
    # Browsers often send .md files as application/octet-stream; fall back to the extension.
    if file.content_type in SUPPORTED_TYPES:
        return file.content_type
    guessed, _ = mimetypes.guess_type(file.filename or "")
    if guessed in SUPPORTED_TYPES:
        return guessed
    raise HTTPException(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF, TXT and Markdown files are supported"
    )


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    business_id: uuid.UUID,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    embedder: EmbedderDep,
):
    """Accepts the file immediately (202) and ingests it in the background.
    Poll the document list to see `status` move from processing → ready."""
    await get_business_or_404(business_id, session)
    content_type = resolve_content_type(file)

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")

    document = Document(
        business_id=business_id,
        filename=file.filename or "untitled",
        content_type=content_type,
    )
    session.add(document)
    await session.commit()

    background_tasks.add_task(ingest_document, document.id, data, SessionLocal, embedder)
    return document


@router.get("", response_model=list[DocumentOut])
async def list_documents(business_id: uuid.UUID, session: SessionDep):
    result = await session.scalars(
        select(Document)
        .where(Document.business_id == business_id)
        .order_by(Document.created_at.desc())
    )
    return result.all()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(business_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep):
    document = await session.get(Document, document_id)
    if document is None or document.business_id != business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    await session.delete(document)
    await session.commit()
