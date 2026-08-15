import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import ADMIN_ONLY, Principal
from app.config import get_settings
from app.db import get_session
from app.ingestion.queue import enqueue_ingest
from app.models import Chunk, Document, DocumentStatus

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".md", ".txt"}


def _document_payload(document: Document, chunk_count: int) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "title": document.title,
        "version": document.version,
        "status": document.status.value,
        "chunk_count": chunk_count,
        "error_message": document.error_message,
        "created_at": document.created_at.isoformat(),
    }


@router.post("/api/documents", status_code=202)
async def upload_document(
    file: UploadFile,
    title: str | None = Form(default=None),
    version: str = Form(default="1"),
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
) -> dict[str, str]:
    org_id = principal.org_id
    settings = get_settings()
    filename = file.filename or "upload"
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file type {extension or '(none)'}; "
            f"accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds the {settings.max_upload_mb} MB upload limit",
        )

    document = Document(
        org_id=org_id,
        title=title or Path(filename).stem,
        version=version,
        status=DocumentStatus.pending,
        file_ref="",
    )
    session.add(document)
    await session.flush()

    target_dir = Path(settings.upload_dir) / str(org_id) / str(document.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"original{extension}"
    target_path.write_bytes(content)
    document.file_ref = str(target_path)
    await session.commit()

    await enqueue_ingest(document.id, org_id)
    return {"id": str(document.id), "status": DocumentStatus.pending.value}


@router.post("/api/documents/{document_id}/reingest", status_code=202)
async def reingest_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
) -> dict[str, str]:
    """Re-run ingestion (recovers worker crashes / stuck `processing`).

    Safe to call in any status: the pipeline deletes and rewrites chunks.
    """
    org_id = principal.org_id
    document = await session.get(Document, document_id)
    if document is None or document.org_id != org_id:
        raise HTTPException(status_code=404, detail="document not found")

    document.status = DocumentStatus.pending
    document.error_message = None
    await session.commit()
    await enqueue_ingest(document.id, org_id)
    return {"id": str(document.id), "status": DocumentStatus.pending.value}


@router.get("/api/documents")
async def list_documents(
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
) -> list[dict[str, Any]]:
    org_id = principal.org_id
    statement = (
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.org_id == org_id)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
    )
    rows = (await session.execute(statement)).all()
    return [_document_payload(document, count) for document, count in rows]


@router.get("/api/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
) -> dict[str, Any]:
    org_id = principal.org_id
    document = await session.get(Document, document_id)
    if document is None or document.org_id != org_id:
        raise HTTPException(status_code=404, detail="document not found")
    chunk_count = (
        await session.execute(select(func.count(Chunk.id)).where(Chunk.document_id == document.id))
    ).scalar_one()
    return _document_payload(document, chunk_count)
