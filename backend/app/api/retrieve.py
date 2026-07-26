"""Dev-only retrieval debug endpoint. Returns 404 in prod (APP_ENV=prod)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_org_id
from app.config import get_settings
from app.db import get_session
from app.rag.retrieve import MAX_K, retrieve

router = APIRouter()


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=MAX_K)


@router.post("/api/retrieve")
async def retrieve_debug(
    payload: RetrieveRequest,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(current_org_id),
) -> list[dict[str, Any]]:
    if get_settings().app_env == "prod":
        raise HTTPException(status_code=404, detail="not found")
    results = await retrieve(session, org_id, payload.query, payload.k)
    return [
        {
            "chunk_id": str(item.chunk_id),
            "score": item.score,
            "text": item.text,
            "document_id": str(item.document_id),
            "document_title": item.document_title,
            "document_version": item.document_version,
            "page": item.page,
            "section": item.section,
        }
        for item in results
    ]
