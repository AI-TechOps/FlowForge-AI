import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.provider import get_provider
from app.models import Chunk, Document, DocumentStatus

MAX_K = 20


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    text: str
    score: float
    document_id: uuid.UUID
    document_title: str
    document_version: str
    page: int | None
    section: str | None


async def retrieve(
    session: AsyncSession, org_id: uuid.UUID, query: str, k: int = 5
) -> list[RetrievedChunk]:
    """Top-k chunks for the org by cosine similarity, with citation metadata.

    Tenant isolation happens directly on the chunk query via the denormalized
    org_id (D7) — chunks from other orgs are structurally unreachable. Only
    `ready` documents participate.
    """
    k = max(1, min(k, MAX_K))
    query_text = query.strip()
    if not query_text:
        return []

    provider = get_provider()
    [query_vector] = await provider.embed([query_text])

    distance = Chunk.embedding.cosine_distance(query_vector)
    statement = (
        select(Chunk, Document, distance.label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.org_id == org_id, Document.status == DocumentStatus.ready)
        .order_by(distance)
        .limit(k)
    )
    rows = (await session.execute(statement)).all()
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            text=chunk.text,
            score=1.0 - float(dist),
            document_id=document.id,
            document_title=document.title,
            document_version=document.version,
            page=chunk.page,
            section=chunk.section,
        )
        for chunk, document, dist in rows
    ]
