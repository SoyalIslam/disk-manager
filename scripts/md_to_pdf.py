#!/usr/bin/env python3
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path


def _escape_pdf_text(s: str) -> str:
    return s.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def markdown_to_plain_lines(md: str, width: int = 96) -> list[str]:
    lines: list[str] = []
    in_code = False
    for raw in md.splitlines():
        line = raw.rstrip("\n")

        if line.strip().startswith("```"):
            in_code = not in_code
            if not in_code:
                lines.append("")
            continue

        if in_code:
            lines.append("    " + line)
            continue

        if line.startswith("#"):
            title = line.lstrip("#").strip()
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(title.upper())
            lines.append("-" * min(len(title), width))
            lines.append("")
            continue

        if line.strip().startswith("- "):
            content = line.strip()[2:].strip()
            wrapped = textwrap.wrap(content, width=max(20, width - 4)) or [""]
            lines.append("  - " + wrapped[0])
            for extra in wrapped[1:]:
                lines.append("    " + extra)
            continue

        if not line.strip():
            if lines and lines[-1] != "":
                lines.append("")
            continue

        wrapped = textwrap.wrap(line.strip(), width=width) or [""]
        lines.extend(wrapped)

    while lines and lines[-1] == "":
        lines.pop()
    return lines


def build_pdf(lines: list[str], output: Path, title: str = "Document") -> None:
    # Simple PDF writer with built-in Helvetica.
    page_w, page_h = 595, 842  # A4 points
    margin_x = 54
    margin_top = 56
    margin_bottom = 56
    font_size = 11
    leading = 14

    usable_h = page_h - margin_top - margin_bottom
    max_lines_per_page = max(1, usable_h // leading)

    pages: list[list[str]] = []
    current: list[str] = []

    current.append(title)
    current.append("")

    for ln in lines:
        if len(current) >= max_lines_per_page:
            pages.append(current)
            current = []
        current.append(ln)

    if current:
        pages.append(current)

    objects: list[bytes] = []

    def add_obj(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    font_obj = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_obj_ids: list[int] = []
    content_obj_ids: list[int] = []

    for p_index, page_lines in enumerate(pages, start=1):
        ops: list[str] = []
        y = page_h - margin_top

        ops.append("BT")
        ops.append(f"/F1 {font_size} Tf")

        for raw in page_lines:
            text = _escape_pdf_text(raw)
            ops.append(f"1 0 0 1 {margin_x} {y} Tm ({text}) Tj")
            y -= leading
            if y < margin_bottom:
                break

        footer = f"Page {p_index} / {len(pages)}"
        ops.append(f"1 0 0 1 {page_w - 130} 30 Tm ({_escape_pdf_text(footer)}) Tj")
        ops.append("ET")

        stream = "\n".join(ops).encode("latin-1", errors="replace")
        content = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        content_id = add_obj(content)
        content_obj_ids.append(content_id)

        page_dict = (
            b"<< /Type /Page /Parent PAGES_REF 0 R /MediaBox [0 0 595 842] "
            + b"/Resources << /Font << /F1 " + str(font_obj).encode("ascii") + b" 0 R >> >> "
            + b"/Contents " + str(content_id).encode("ascii") + b" 0 R >>"
        )
        page_id = add_obj(page_dict)
        page_obj_ids.append(page_id)

    kids = b"[ " + b" ".join(str(pid).encode("ascii") + b" 0 R" for pid in page_obj_ids) + b" ]"
    pages_obj = add_obj(b"<< /Type /Pages /Kids " + kids + b" /Count " + str(len(page_obj_ids)).encode("ascii") + b" >>")

    # Patch parent references.
    for pid in page_obj_ids:
        idx = pid - 1
        objects[idx] = objects[idx].replace(b"PAGES_REF", str(pages_obj).encode("ascii"))

    catalog_obj = add_obj(b"<< /Type /Catalog /Pages " + str(pages_obj).encode("ascii") + b" 0 R >>")

    # Build xref.
    out = bytearray()
    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    trailer = (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode("ascii")
        + b" /Root "
        + str(catalog_obj).encode("ascii")
        + b" 0 R >>\nstartxref\n"
        + str(xref_pos).encode("ascii")
        + b"\n%%EOF\n"
    )
    out.extend(trailer)

    output.write_bytes(bytes(out))


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert markdown-like text to a simple PDF (no external deps).")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", default="Diskman Detailed Guide")
    args = parser.parse_args()

    src = args.input.read_text(encoding="utf-8")
    lines = markdown_to_plain_lines(src)
    build_pdf(lines, args.output, title=args.title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
