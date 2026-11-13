"""Build the Adapter Experiment Report .docx from its Markdown source.

No pandoc dependency: this script handles the small Markdown subset used by
``docs/reports/Adapter-Experiment-Report.md`` (headings, paragraphs, bullet and
numbered lists, fenced code, blockquotes, and pipe tables).
"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "docs" / "reports" / "Adapter-Experiment-Report.md"
TARGET = REPO / "docs" / "reports" / "Adapter-Experiment-Report.docx"

INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")


def set_font(run, name: str = "Microsoft YaHei", size: int | None = None,
             bold: bool | None = None, italic: bool | None = None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic


def add_inline(paragraph, text: str, size: int | None = None):
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            set_font(run, size=size, bold=True)
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            set_font(run, name="Consolas", size=size)
        elif part.startswith("[") and "](" in part:
            label, url = part[1:].split("](", 1)
            run = paragraph.add_run(f"{label} ({url.rstrip(')')})")
            set_font(run, size=size)
        else:
            run = paragraph.add_run(part)
            set_font(run, size=size)


def parse_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell or "-") for cell in cells):
            continue
        rows.append(cells)
    return rows


def build():
    text = SOURCE.read_text(encoding="utf-8")
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    lines = text.splitlines()
    i = 0
    in_code = False
    code: list[str] = []
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            if in_code:
                paragraph = doc.add_paragraph()
                paragraph.paragraph_format.space_after = Pt(2)
                run = paragraph.add_run("\n".join(code))
                set_font(run, name="Consolas", size=9)
                code.clear()
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code.append(line)
            i += 1
            continue
        stripped = line.strip()
        if not stripped or stripped == "---":
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            rows = parse_table(block)
            if not rows:
                continue
            table = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
            table.style = "Table Grid"
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    cell = table.cell(r, c)
                    cell.text = ""
                    paragraph = cell.paragraphs[0]
                    add_inline(paragraph, value, size=9)
                    if r == 0:
                        for run in paragraph.runs:
                            run.bold = True
            doc.add_paragraph()
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            paragraph = doc.add_heading(level=level)
            add_inline(paragraph, heading.group(2), size=18 if level == 1 else 14 if level == 2 else 11)
            i += 1
            continue
        if stripped.startswith("> "):
            paragraph = doc.add_paragraph()
            add_inline(paragraph, stripped[2:], size=9)
            for run in paragraph.runs:
                run.italic = True
            i += 1
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            paragraph = doc.add_paragraph(style="List Bullet")
            add_inline(paragraph, bullet.group(1))
            i += 1
            continue
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            paragraph = doc.add_paragraph(style="List Number")
            add_inline(paragraph, numbered.group(1))
            i += 1
            continue
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(4)
        add_inline(paragraph, stripped)
        i += 1

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    doc.save(TARGET)
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    build()
