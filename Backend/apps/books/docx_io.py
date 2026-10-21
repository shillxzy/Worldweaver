"""DOCX import/export.

Declared support (first version): paragraphs, headings (Heading 1-3 / Title), bold,
italic, underline, strike-through, line breaks, simple bulleted/numbered lists (as
plain list items). Tables, footnotes, comments, headers/footers, images, text boxes and
tracked changes are NOT converted; their text may be skipped. Macros are never
executed: python-docx only reads the XML parts of the package, and ``.docm`` files are
rejected by content type.
"""
import io
import re
import zipfile

from django.conf import settings
from docx import Document
from docx.enum.text import WD_BREAK
from docx.opc.exceptions import PackageNotFoundError
from docx.shared import Pt
from rest_framework.exceptions import ValidationError

DOCX_MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
HEADING_RE = re.compile(r"^(heading|заголовок)\s*(\d)$", re.IGNORECASE)


class DocxError(ValidationError):
    pass


def _check_package(raw: bytes):
    if len(raw) > settings.WW_MAX_DOCX_BYTES:
        raise DocxError({"file": f"Файл завеликий (максимум {settings.WW_MAX_DOCX_BYTES // 1024 // 1024} МБ)."})
    if len(raw) == 0:
        raise DocxError({"file": "Файл порожній."})
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            total = sum(info.file_size for info in archive.infolist())
            if total > settings.WW_MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocxError({"file": "Розпакований документ завеликий."})
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names:
                raise DocxError({"file": "Файл не є документом Word (.docx)."})
            content_types = archive.read("[Content_Types].xml").decode("utf-8", "replace")
            if DOCX_MAIN_TYPE not in content_types:
                raise DocxError({"file": "Підтримуються лише документи .docx без макросів."})
    except zipfile.BadZipFile as exc:
        raise DocxError({"file": "Файл пошкоджений або не є .docx."}) from exc


def _heading_level(paragraph):
    style_name = (paragraph.style.name if paragraph.style is not None else "") or ""
    if style_name.lower() == "title":
        return 1
    match = HEADING_RE.match(style_name.strip())
    if match:
        return max(1, min(3, int(match.group(2))))
    return None


def _is_list(paragraph):
    style_name = (paragraph.style.name if paragraph.style is not None else "") or ""
    if "list" in style_name.lower():
        return True
    ppr = paragraph._p.pPr
    return ppr is not None and ppr.numPr is not None


def _runs_to_inline(paragraph):
    inline = []
    for run in paragraph.runs:
        marks = []
        if run.bold:
            marks.append({"type": "bold"})
        if run.italic:
            marks.append({"type": "italic"})
        if run.underline:
            marks.append({"type": "underline"})
        if run.font is not None and run.font.strike:
            marks.append({"type": "strike"})
        parts = run.text.replace("\r", "").split("\n")
        for i, part in enumerate(parts):
            if i:
                inline.append({"type": "hardBreak"})
            if part:
                node = {"type": "text", "text": part.replace("\t", "    ")}
                if marks:
                    node["marks"] = [dict(m) for m in marks]
                if inline and inline[-1].get("type") == "text" and inline[-1].get("marks") == node.get("marks"):
                    inline[-1]["text"] += node["text"]
                else:
                    inline.append(node)
    return inline


def parse_docx(raw: bytes):
    """Return a list of blocks: dicts with type 'heading'(level)/'paragraph'/'list_item' and inline content."""
    _check_package(raw)
    try:
        document = Document(io.BytesIO(raw))
    except (PackageNotFoundError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise DocxError({"file": "Не вдалося прочитати документ: файл пошкоджений."}) from exc
    except Exception as exc:  # python-docx raises assorted lxml/parsing errors on broken XML
        raise DocxError({"file": "Не вдалося прочитати документ: некоректна структура."}) from exc

    blocks = []
    for paragraph in document.paragraphs:
        inline = _runs_to_inline(paragraph)
        has_text = any(n["type"] == "text" and n["text"].strip() for n in inline)
        if not has_text:
            continue
        level = _heading_level(paragraph)
        if level:
            blocks.append({"type": "heading", "level": level, "content": inline})
        elif _is_list(paragraph):
            blocks.append({"type": "list_item", "content": inline})
        else:
            blocks.append({"type": "paragraph", "content": inline})
    if not blocks:
        raise DocxError({"file": "Документ не містить тексту."})
    return blocks


def blocks_to_document(blocks):
    content = []
    pending_list = None
    for block in blocks:
        if block["type"] == "list_item":
            if pending_list is None:
                pending_list = {"type": "bulletList", "content": []}
                content.append(pending_list)
            pending_list["content"].append({"type": "listItem", "content": [{"type": "paragraph", "content": block["content"]}]})
            continue
        pending_list = None
        if block["type"] == "heading":
            content.append({"type": "heading", "attrs": {"level": block["level"]}, "content": block["content"]})
        else:
            content.append({"type": "paragraph", "content": block["content"]})
    return {"type": "doc", "content": content or [{"type": "paragraph"}]}


def _plain(inline):
    return "".join(n.get("text", "") for n in inline).strip()


def split_by_headings(blocks, default_title):
    """Split blocks into chapters on level-1 headings (or the top-most heading level used)."""
    levels = [b["level"] for b in blocks if b["type"] == "heading"]
    if not levels:
        return [(default_title, blocks_to_document(blocks))]
    split_level = min(levels)
    chapters, title, current = [], None, []
    for block in blocks:
        if block["type"] == "heading" and block["level"] == split_level:
            if current or title:
                chapters.append((title or default_title, blocks_to_document(current)))
            title, current = _plain(block["content"])[:200] or default_title, []
        else:
            current.append(block)
    if current or title:
        chapters.append((title or default_title, blocks_to_document(current)))
    return chapters


# --- export -------------------------------------------------------------------

def _add_inline(paragraph, nodes):
    for node in nodes or []:
        if node["type"] == "hardBreak":
            if paragraph.runs:
                paragraph.runs[-1].add_break(WD_BREAK.LINE)
            else:
                paragraph.add_run().add_break(WD_BREAK.LINE)
            continue
        if node["type"] != "text":
            continue
        run = paragraph.add_run(node["text"])
        marks = {m["type"] for m in node.get("marks", [])}
        run.bold = "bold" in marks or None
        run.italic = "italic" in marks or None
        run.underline = "underline" in marks or None
        if "strike" in marks:
            run.font.strike = True


def _write_blocks(document, node, list_style=None):
    node_type = node["type"]
    if node_type == "heading":
        level = node.get("attrs", {}).get("level", 2)
        paragraph = document.add_heading(level=min(3, level + 1))
        _add_inline(paragraph, node.get("content"))
    elif node_type == "paragraph":
        paragraph = document.add_paragraph(style=list_style) if list_style else document.add_paragraph()
        _add_inline(paragraph, node.get("content"))
    elif node_type == "horizontalRule":
        paragraph = document.add_paragraph("* * *")
        paragraph.alignment = 1
    elif node_type in ("bulletList", "orderedList"):
        style = "List Bullet" if node_type == "bulletList" else "List Number"
        for item in node.get("content", []):
            for child in item.get("content", []):
                _write_blocks(document, child, style)
    elif node_type == "blockquote":
        for child in node.get("content", []):
            _write_blocks(document, child, "Quote" if child["type"] == "paragraph" else None)
    else:
        for child in node.get("content", []):
            _write_blocks(document, child, list_style)


def export_docx(title, chapters):
    """chapters: iterable of (chapter_title, tiptap_document). Returns bytes."""
    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    if title:
        document.add_heading(title, level=0)
    for index, (chapter_title, content) in enumerate(chapters):
        if index and title:
            document.add_page_break()
        document.add_heading(chapter_title, level=1)
        _write_blocks(document, content)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
