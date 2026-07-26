"""Text extraction preserving citation metadata (page / section).

PDF: per-page text via pypdf (text-layer PDFs only — OCR is out of scope).
Markdown: blocks grouped under their nearest heading.
Plain text: one block, no page/section.
"""

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractedBlock:
    text: str
    page: int | None = None
    section: str | None = None


def extract(path: Path) -> list[ExtractedBlock]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".md":
        return _extract_markdown(path)
    if suffix == ".txt":
        return _extract_text(path)
    raise ValueError(f"unsupported file type: {suffix or '(none)'}")


def _extract_pdf(path: Path) -> list[ExtractedBlock]:
    try:
        reader = PdfReader(path)
        blocks = [
            ExtractedBlock(text=page.extract_text() or "", page=number)
            for number, page in enumerate(reader.pages, start=1)
        ]
    except Exception as exc:
        raise ValueError(f"cannot read PDF: {exc}") from exc
    blocks = [block for block in blocks if block.text.strip()]
    if not blocks:
        raise ValueError("PDF contains no extractable text (scanned/OCR unsupported)")
    return blocks


def _extract_markdown(path: Path) -> list[ExtractedBlock]:
    section: str | None = None
    lines_in_section: list[str] = []
    blocks: list[ExtractedBlock] = []

    def flush() -> None:
        text = "\n".join(lines_in_section).strip()
        if text:
            blocks.append(ExtractedBlock(text=text, section=section))
        lines_in_section.clear()

    for line in _read_utf8(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            section = stripped.lstrip("#").strip() or section
        else:
            lines_in_section.append(line)
    flush()

    if not blocks:
        raise ValueError("Markdown file contains no text content")
    return blocks


def _extract_text(path: Path) -> list[ExtractedBlock]:
    text = _read_utf8(path).strip()
    if not text:
        raise ValueError("text file is empty")
    return [ExtractedBlock(text=text)]


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"file is not valid UTF-8 text: {exc}") from exc
