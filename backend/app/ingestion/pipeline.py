"""Ingestion pipeline: extract → chunk → embed → store.

Idempotent: each run deletes and rewrites the document's chunks, so retries
and reingests can never duplicate. Every failure path lands the document in
`failed` with a human-readable error_message — never a stuck `processing`.
"""

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete

from app.config import get_settings
from app.db import async_session_factory
from app.ingestion.chunk import chunk_blocks
from app.ingestion.extract import extract
from app.llm.provider import get_provider
from app.models import Chunk, Document, DocumentStatus

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32


async def ingest_document(ctx: dict[str, Any], document_id: str, org_id: str) -> str:
    """arq job entrypoint. Returns the final document status."""
    doc_uuid = uuid.UUID(document_id)
    org_uuid = uuid.UUID(org_id)

    async with async_session_factory() as session:
        document = await session.get(Document, doc_uuid)
        if document is None or document.org_id != org_uuid:
            logger.warning("ingest skipped: document %s not found in org %s", document_id, org_id)
            return "missing"

        document.status = DocumentStatus.processing
        document.error_message = None
        await session.commit()

        try:
            blocks = extract(Path(document.file_ref))
            drafts = chunk_blocks(blocks)
            if not drafts:
                raise ValueError("document produced no chunks")

            provider = get_provider()
            embeddings: list[list[float]] = []
            for start in range(0, len(drafts), EMBED_BATCH_SIZE):
                batch = drafts[start : start + EMBED_BATCH_SIZE]
                embeddings.extend(await provider.embed([d.text for d in batch]))

            model_name = get_settings().embedding_model
            await session.execute(delete(Chunk).where(Chunk.document_id == doc_uuid))
            session.add_all(
                Chunk(
                    org_id=org_uuid,
                    document_id=doc_uuid,
                    chunk_index=draft.chunk_index,
                    text=draft.text,
                    embedding=vector,
                    embedding_model=model_name,
                    page=draft.page,
                    section=draft.section,
                    token_count=draft.token_count,
                )
                for draft, vector in zip(drafts, embeddings, strict=True)
            )
            document.status = DocumentStatus.ready
            await session.commit()
            logger.info("ingested document %s: %d chunks", document_id, len(drafts))
            return DocumentStatus.ready.value
        except Exception as exc:
            await session.rollback()
            document.status = DocumentStatus.failed
            document.error_message = str(exc)[:2000]
            await session.commit()
            logger.exception("ingestion failed for document %s", document_id)
            return DocumentStatus.failed.value
