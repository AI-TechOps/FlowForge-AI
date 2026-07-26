"""Generate the Meridian Dynamics text-layer PDF fixtures.

The committed Markdown sources remain the reviewable source of truth. This
script uses only the Python standard library so fixture regeneration does not
depend on a workstation PDF renderer.
"""

from __future__ import annotations

import argparse
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
LEFT_MARGIN = 54
TOP_Y = 738
BOTTOM_Y = 54
BODY_FONT_SIZE = 9
HEADING_FONT_SIZE = 11
LINE_HEIGHT = 13
WRAP_WIDTH = 94


@dataclass(frozen=True)
class RenderLine:
    text: str
    bold: bool = False


SOURCE_TO_OUTPUT = {
    "vpn-access-policy.source.md": "MD-IT-001-vpn-access-policy.pdf",
    "incident-priority-escalation.source.md": (
        "MD-IT-002-incident-priority-escalation-guidelines.pdf"
    ),
    "security-incident-reporting.source.md": (
        "MD-IT-008-security-incident-reporting-policy.pdf"
    ),
}


def _display_lines(markdown: str) -> list[RenderLine]:
    lines: list[RenderLine] = []
    in_front_matter = False
    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        if stripped == "---":
            in_front_matter = not in_front_matter
            continue
        if in_front_matter:
            key, separator, value = stripped.partition(":")
            if separator:
                label = key.replace("_", " ").title()
                lines.append(RenderLine(f"{label}: {value.strip()}", bold=True))
            continue
        if not stripped:
            lines.append(RenderLine(""))
            continue

        heading = re.match(r"^#{1,3}\s+(.+)$", stripped)
        if heading:
            lines.append(RenderLine(heading.group(1), bold=True))
            continue

        list_item = re.match(r"^(\d+\.)\s+(.+)$", stripped)
        prefix = f"{list_item.group(1)} " if list_item else ""
        text = list_item.group(2) if list_item else stripped
        text = text.replace("**", "").replace("`", "")
        wrapped = textwrap.wrap(
            text,
            width=WRAP_WIDTH - len(prefix),
            break_long_words=False,
            break_on_hyphens=False,
        )
        for index, part in enumerate(wrapped or [""]):
            lines.append(RenderLine(f"{prefix if index == 0 else '   '}{part}"))

    compacted: list[RenderLine] = []
    for line in lines:
        if line.text or not compacted or compacted[-1].text:
            compacted.append(line)
    return compacted


def _paginate(lines: list[RenderLine]) -> list[list[RenderLine]]:
    usable_lines = int((TOP_Y - BOTTOM_Y) / LINE_HEIGHT)
    pages: list[list[RenderLine]] = []
    current: list[RenderLine] = []
    for line in lines:
        if len(current) >= usable_lines:
            pages.append(current)
            current = []
        current.append(line)
    if current:
        pages.append(current)
    return pages


def _pdf_text(text: str) -> bytes:
    encoded = text.encode("cp1252", errors="replace")
    return encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _page_stream(lines: list[RenderLine], page_number: int, page_count: int) -> bytes:
    commands: list[bytes] = []
    y = TOP_Y
    for line in lines:
        font = b"F2" if line.bold else b"F1"
        size = HEADING_FONT_SIZE if line.bold else BODY_FONT_SIZE
        commands.extend(
            [
                b"BT",
                f"/{font.decode()} {size} Tf".encode(),
                f"1 0 0 1 {LEFT_MARGIN} {y} Tm".encode(),
                b"(" + _pdf_text(line.text) + b") Tj",
                b"ET",
            ]
        )
        y -= LINE_HEIGHT
    footer = f"Meridian Dynamics | Page {page_number} of {page_count}"
    commands.extend(
        [
            b"BT",
            b"/F1 8 Tf",
            f"1 0 0 1 {LEFT_MARGIN} 30 Tm".encode(),
            b"(" + _pdf_text(footer) + b") Tj",
            b"ET",
        ]
    )
    return b"\n".join(commands)


def _pdf_object(payload: bytes) -> bytes:
    return (
        b"<< /Length "
        + str(len(payload)).encode()
        + b" >>\nstream\n"
        + payload
        + (b"\nendstream")
    )


def _build_pdf(markdown: str, title: str) -> bytes:
    pages = _paginate(_display_lines(markdown))
    page_object_numbers = [5 + index * 2 for index in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            b"<< /Type /Pages /Count "
            + str(len(pages)).encode()
            + b" /Kids ["
            + b" ".join(f"{number} 0 R".encode() for number in page_object_numbers)
            + b"] >>"
        ),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    }
    for index, page in enumerate(pages):
        page_number = 5 + index * 2
        stream_number = page_number + 1
        objects[page_number] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + str(PAGE_WIDTH).encode()
            + b" "
            + str(PAGE_HEIGHT).encode()
            + b"] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            + f"/Contents {stream_number} 0 R >>".encode()
        )
        objects[stream_number] = _pdf_object(_page_stream(page, index + 1, len(pages)))

    info_number = max(objects) + 1
    objects[info_number] = (
        b"<< /Title (" + _pdf_text(title) + b") /Author (Meridian Dynamics, Inc.) "
        b"/Subject (Fictional enterprise IT policy fixture) >>"
    )

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max(objects) + 1)
    for number in sorted(objects):
        offsets[number] = len(output)
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(objects[number])
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        b"trailer\n<< /Size "
        + str(len(offsets)).encode()
        + b" /Root 1 0 R /Info "
        + str(info_number).encode()
        + b" 0 R >>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return bytes(output)


def generate(repository_root: Path, *, check: bool) -> int:
    enterprise = repository_root / "fixtures" / "enterprise"
    sources = enterprise / "sources"
    stale: list[Path] = []
    for source_name, output_name in SOURCE_TO_OUTPUT.items():
        source = sources / source_name
        output = enterprise / output_name
        markdown = source.read_text(encoding="utf-8")
        title_match = re.search(r"^title:\s*(.+)$", markdown, flags=re.MULTILINE)
        if title_match is None:
            raise ValueError(f"{source} has no title front-matter field")
        expected = _build_pdf(markdown, title_match.group(1).strip())
        if check:
            if not output.is_file() or output.read_bytes() != expected:
                stale.append(output)
        else:
            output.write_bytes(expected)
            print(f"generated {output.relative_to(repository_root)}")
    if stale:
        for path in stale:
            print(f"stale or missing: {path.relative_to(repository_root)}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if committed PDFs differ from their Markdown sources",
    )
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    return generate(repository_root, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
