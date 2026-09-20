"""Report export: Markdown -> PPTX / DOCX (python-pptx, python-docx).

The converter covers the report structure our prompt generates: #/##/###
headings, paragraphs, bullet lists, and embedded chart images. Anything more
exotic degrades gracefully to plain text.
"""

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


def _parse_blocks(markdown: str) -> list[tuple[str, str, str]]:
    """Yield (kind, level, content) blocks: heading/paragraph/bullet/image."""
    blocks: list[tuple[str, str, str]] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("![" ):
            match = re.match(r"!\[(.*?)\]\((.*?)\)", stripped)
            if match:
                blocks.append(("image", "", f"{match.group(1)}|{match.group(2)}"))
        elif stripped.startswith("### "):
            blocks.append(("heading", "3", stripped[4:]))
        elif stripped.startswith("## "):
            blocks.append(("heading", "2", stripped[3:]))
        elif stripped.startswith("# "):
            blocks.append(("heading", "1", stripped[2:]))
        elif re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            blocks.append(("bullet", "", re.sub(r"^([-*]|\d+\.)\s+", "", stripped)))
        else:
            blocks.append(("paragraph", "", stripped))
    return blocks


def _resolve_image(base_dir: str, ref: str) -> str | None:
    path = os.path.normpath(os.path.join(base_dir, ref))
    return path if os.path.isfile(path) else None


def markdown_to_pptx(markdown: str, out_path: str, base_dir: str = ".") -> str:
    """Render report structure to slides; H1/H2 open new slides."""
    from pptx import Presentation
    from pptx.util import Pt

    prs = Presentation()

    def new_slide(title_text: str) -> Any:  # noqa: ANN401 — pptx types are dynamic
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title_text[:120]
        return slide.placeholders[1].text_frame

    slide_body = None
    title = "Research Report"
    for kind, level, content in _parse_blocks(markdown):
        if kind == "heading" and level in ("1", "2"):
            slide_body = new_slide(content)
            title = content
        elif kind == "heading" and level == "3":
            if slide_body is None:
                slide_body = new_slide(title)
            slide_body.add_paragraph().text = content
        elif kind == "bullet":
            if slide_body is None:
                slide_body = new_slide(title)
            p = slide_body.add_paragraph()
            p.text = "• " + content[:300]
            p.font.size = Pt(14)
        elif kind == "image":
            img_title, ref = content.split("|", 1)
            img_path = _resolve_image(base_dir, ref)
            if img_path:
                slide = prs.slides.add_slide(prs.slide_layouts[5])  # title-only
                slide.shapes.title.text = (img_title or "Chart")[:120]
                slide.shapes.add_picture(img_path, 0, prs.slide_height * 0.2,
                                         width=prs.slide_width)
        elif kind == "paragraph":
            if slide_body is None:
                slide_body = new_slide(title)
            p = slide_body.add_paragraph()
            p.text = content[:300]
            p.font.size = Pt(14)

    prs.save(out_path)
    return out_path


def markdown_to_docx(markdown: str, out_path: str, base_dir: str = ".") -> str:
    """Render report structure to a Word document."""
    import docx

    document = docx.Document()
    for kind, level, content in _parse_blocks(markdown):
        if kind == "heading":
            document.add_heading(content, level=int(level))
        elif kind == "bullet":
            document.add_paragraph(content, style="List Bullet")
        elif kind == "image":
            img_title, ref = content.split("|", 1)
            img_path = _resolve_image(base_dir, ref)
            if img_path:
                document.add_picture(img_path, width=docx.shared.Inches(6))
                document.add_paragraph(img_title).alignment = 1  # center
        else:
            document.add_paragraph(content)
    document.save(out_path)
    return out_path


EXPORTERS = {"pptx": markdown_to_pptx, "docx": markdown_to_docx}
