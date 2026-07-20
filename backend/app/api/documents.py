import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_org_id
from app.config import get_settings
from app.db import get_session
from app.ingestion.queue import enqueue_ingest
from app.models import Document, DocumentStatus

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".md", ".txt"}


@router.post("/api/documents", status_code=202)
async def upload_document(
    file: UploadFile,
    title: str | None = Form(default=None),
    version: str = Form(default="1"),
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(current_org_id),
) -> dict[str, str]:
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
