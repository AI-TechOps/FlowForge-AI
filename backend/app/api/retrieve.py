"""Dev-only retrieval debug endpoint. Returns 404 in prod (APP_ENV=prod)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AliasChoices, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import ADMIN_ONLY, Principal
from app.config import get_settings
from app.db import get_session
from app.rag.retrieve import MAX_K, retrieve

router = APIRouter()


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    # `top_k` is accepted as an alias because that is the name the rest of the
    # world uses for this parameter; without it a caller asking for 20 results
    # silently gets the default 5.
    k: int = Field(default=5, ge=1, le=MAX_K, validation_alias=AliasChoices("k", "top_k"))


@router.post("/api/retrieve")
async def retrieve_debug(
    payload: RetrieveRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = ADMIN_ONLY,
) -> list[dict[str, Any]]:
    if get_settings().app_env == "prod":
        raise HTTPException(status_code=404, detail="not found")
    results = await retrieve(session, principal.org_id, payload.query, payload.k)
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
