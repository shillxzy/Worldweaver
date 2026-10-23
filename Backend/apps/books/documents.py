"""Server-side validation and text extraction for Tiptap / ProseMirror JSON documents.

The client is not trusted: only a whitelisted subset of node types, marks and
attributes is accepted, depth and size are bounded, and nothing in the document is
ever executed or rendered as HTML on the server.
"""
import json
import re

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.common.text import count_words

BLOCK_NODES = {"paragraph", "heading", "blockquote", "bulletList", "orderedList", "listItem", "horizontalRule"}
INLINE_NODES = {"text", "hardBreak"}
ALLOWED_NODES = {"doc"} | BLOCK_NODES | INLINE_NODES
ALLOWED_MARKS = {"bold", "italic", "underline", "strike", "link"}
# Internal links point to encyclopedia pages ("page:<id>"); external links only http(s)/mailto.
LINK_HREF_RE = re.compile(r"^(page:\d{1,18}|https?://[^\s<>\"']{1,2000}|mailto:[^\s<>\"']{1,320})$")
ALLOWED_ATTRS = {
    "heading": {"level": lambda v: isinstance(v, int) and 1 <= v <= 3, "textAlign": lambda v: v in (None, "left", "center", "right", "justify")},
    "paragraph": {"textAlign": lambda v: v in (None, "left", "center", "right", "justify")},
    "orderedList": {"start": lambda v: isinstance(v, int) and 0 <= v <= 100000, "type": lambda v: v is None or isinstance(v, str) and len(v) <= 4},
}
MAX_DEPTH = 12
MAX_NODES = 200_000


def _fail(message):
    raise ValidationError({"content": [message]})


def validate_document(doc):
    """Validate a Tiptap JSON document. Returns a cleaned copy or raises ValidationError."""
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        _fail("Документ має бути обʼєктом із type='doc'.")
    raw_size = len(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    if raw_size > settings.WW_MAX_DOCUMENT_BYTES:
        _fail(f"Документ завеликий ({raw_size} байт).")

    counter = {"nodes": 0}

    def clean(node, depth):
        if depth > MAX_DEPTH:
            _fail("Документ має надто глибоку вкладеність.")
        if not isinstance(node, dict):
            _fail("Вузол документа має бути обʼєктом.")
        counter["nodes"] += 1
        if counter["nodes"] > MAX_NODES:
            _fail("Документ містить забагато вузлів.")
        node_type = node.get("type")
        if node_type not in ALLOWED_NODES:
            _fail(f"Недозволений тип вузла: {str(node_type)[:40]!r}.")
        out = {"type": node_type}
        if node_type == "text":
            text = node.get("text")
            if not isinstance(text, str) or not text:
                _fail("Текстовий вузол має містити непорожній рядок.")
            out["text"] = text
            marks = node.get("marks") or []
            if not isinstance(marks, list):
                _fail("marks має бути списком.")
            clean_marks = []
            for mark in marks:
                if not isinstance(mark, dict) or mark.get("type") not in ALLOWED_MARKS:
                    _fail("Недозволене форматування тексту.")
                if mark["type"] == "link":
                    href = (mark.get("attrs") or {}).get("href")
                    if not isinstance(href, str) or not LINK_HREF_RE.match(href):
                        _fail("Недозволене посилання: дозволені сторінки енциклопедії, http(s) і mailto.")
                    clean_marks.append({"type": "link", "attrs": {"href": href}})
                    continue
                clean_marks.append({"type": mark["type"]})
            if clean_marks:
                out["marks"] = clean_marks
            return out
        attrs = node.get("attrs")
        if attrs is not None:
            if not isinstance(attrs, dict):
                _fail("attrs має бути обʼєктом.")
            allowed = ALLOWED_ATTRS.get(node_type, {})
            clean_attrs = {}
            for key, value in attrs.items():
                check = allowed.get(key)
                if check is None:
                    continue  # silently drop unknown attributes
                if not check(value):
                    _fail(f"Некоректний атрибут {key} для {node_type}.")
                clean_attrs[key] = value
            if node_type == "heading" and "level" not in clean_attrs:
                clean_attrs["level"] = 2
            if clean_attrs:
                out["attrs"] = clean_attrs
        elif node_type == "heading":
            out["attrs"] = {"level": 2}
        content = node.get("content")
        if content is not None:
            if not isinstance(content, list):
                _fail("content має бути списком.")
            if node_type in ("hardBreak", "horizontalRule") and content:
                _fail(f"{node_type} не може мати вмісту.")
            out["content"] = [clean(child, depth + 1) for child in content]
        return out

    cleaned = clean(doc, 0)
    for child in cleaned.get("content", []):
        if child["type"] not in BLOCK_NODES - {"listItem"}:
            _fail("На верхньому рівні дозволені лише блокові елементи.")
    if not cleaned.get("content"):
        cleaned["content"] = [{"type": "paragraph"}]
    return cleaned


def _inline_text(node):
    if node["type"] == "text":
        return node["text"]
    if node["type"] == "hardBreak":
        return "\n"
    return "".join(_inline_text(c) for c in node.get("content", []))


def extract_blocks(doc):
    """Yield (block_type, text, attrs) for every text block in reading order."""
    def walk(node, list_prefix=""):
        node_type = node["type"]
        if node_type in ("paragraph", "heading"):
            yield node_type, list_prefix + _inline_text(node), node.get("attrs", {})
        elif node_type == "horizontalRule":
            yield "horizontalRule", "* * *", {}
        elif node_type in ("bulletList", "orderedList"):
            for i, item in enumerate(node.get("content", []), start=1):
                prefix = "• " if node_type == "bulletList" else f"{i}. "
                for child in item.get("content", []):
                    yield from walk(child, prefix)
                    prefix = ""
        else:
            for child in node.get("content", []):
                yield from walk(child, list_prefix)

    yield from walk(doc)


def document_to_text(doc) -> str:
    return "\n\n".join(text for _, text, _ in extract_blocks(doc)).strip()


def text_to_document(text: str) -> dict:
    paragraphs = [p.strip() for p in (text or "").replace("\r\n", "\n").split("\n\n")]
    content = []
    for para in paragraphs:
        if not para:
            continue
        inline = []
        for i, line in enumerate(para.split("\n")):
            if i:
                inline.append({"type": "hardBreak"})
            if line:
                inline.append({"type": "text", "text": line})
        content.append({"type": "paragraph", "content": inline} if inline else {"type": "paragraph"})
    return {"type": "doc", "content": content or [{"type": "paragraph"}]}


def document_stats(doc):
    text = document_to_text(doc)
    return text, count_words(text)


def page_link_ids(doc):
    """Ids of encyclopedia pages referenced by link marks (``href="page:<id>"``)."""
    ids = []

    def walk(node):
        for mark in node.get("marks", []) or []:
            href = (mark.get("attrs") or {}).get("href", "") if mark.get("type") == "link" else ""
            if href.startswith("page:"):
                ids.append(int(href[5:]))
        for child in node.get("content", []) or []:
            walk(child)

    walk(doc)
    return list(dict.fromkeys(ids))
