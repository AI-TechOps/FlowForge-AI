"""Overlapping-window chunking over extracted blocks.

Token counts are whitespace-word approximations — good enough for window
sizing and provider-agnostic (no tokenizer dependency). Window sizes come
from config (CHUNK_TARGET_TOKENS / CHUNK_OVERLAP_TOKENS), never hardcoded.
"""

from dataclasses import dataclass

from app.config import get_settings
from app.ingestion.extract import ExtractedBlock


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    text: str
    token_count: int
    page: int | None
    section: str | None


def chunk_blocks(blocks: list[ExtractedBlock]) -> list[ChunkDraft]:
    settings = get_settings()
    target = max(1, settings.chunk_target_tokens)
    overlap = min(max(0, settings.chunk_overlap_tokens), target - 1)

    drafts: list[ChunkDraft] = []
    for block in blocks:
        words = block.text.split()
        if not words:
            continue
        step = target - overlap
        start = 0
        while start < len(words):
            window = words[start : start + target]
            drafts.append(
                ChunkDraft(
                    chunk_index=len(drafts),
                    text=" ".join(window),
                    token_count=len(window),
                    page=block.page,
                    section=block.section,
                )
            )
            if start + target >= len(words):
                break
            start += step
    return drafts
