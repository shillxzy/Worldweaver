"""Public read-only site of a world (``/public/<token>/...``), for anyone with the link.

Nothing is public by default: the owner turns the site on and marks books, chapters and pages
one by one. Everything else stays invisible — links to hidden pages lose their link and become
plain text, page-type properties skip hidden pages, and hidden ids answer 404.
"""
import copy

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.books.models import Book, Chapter
from apps.common.images import image_response
from apps.pages.models import Page, PageProperty
from apps.worlds.models import World


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # anonymous by design: no session, no CSRF
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public"

    def world(self, token):
        return get_object_or_404(World, public_enabled=True, public_token=token)


def public_chapters(world):
    return Chapter.objects.filter(book__world=world, book__is_public=True, is_public=True)


def public_page_ids(world):
    return set(Page.objects.filter(world=world, is_public=True).values_list("id", flat=True))


def strip_hidden_links(doc, visible):
    """Copy of a document where links to non-public pages are removed (the text stays)."""
    doc = copy.deepcopy(doc or {"type": "doc", "content": []})

    def walk(node):
        marks = node.get("marks")
        if marks:
            kept = []
            for mark in marks:
                href = (mark.get("attrs") or {}).get("href", "") if mark.get("type") == "link" else ""
                if href.startswith("page:") and not (href[5:].isdigit() and int(href[5:]) in visible):
                    continue
                kept.append(mark)
            if kept:
                node["marks"] = kept
            else:
                node.pop("marks")
        for child in node.get("content", []) or []:
            walk(child)

    walk(doc)
    return doc


def public_parent(page, by_id, visible):
    """Nearest public ancestor (hidden pages in between are skipped)."""
    seen = set()
    parent_id = page["parent"]
    while parent_id is not None and parent_id not in seen:
        seen.add(parent_id)
        if parent_id in visible:
            return parent_id
        parent_id = by_id[parent_id]["parent"] if parent_id in by_id else None
    return None


class PublicWorldView(PublicView):
    @extend_schema(responses=None)
    def get(self, request, token):
        world = self.world(token)
        chapters = {}
        for c in public_chapters(world).order_by("order", "id").values("id", "book_id", "title", "word_count"):
            chapters.setdefault(c["book_id"], []).append({"id": c["id"], "title": c["title"], "word_count": c["word_count"]})
        books = [
            {"id": b.id, "title": b.title, "description": b.description, "genre": b.genre, "accent": b.accent,
             "has_cover": bool(b.cover), "updated_at": b.updated_at, "chapters": chapters.get(b.id, [])}
            for b in Book.objects.filter(world=world, is_public=True).order_by("title")
        ]
        all_pages = {p["id"]: p for p in Page.objects.filter(world=world).values("id", "parent", "title", "icon", "page_type", "sort_order", "is_public")}
        visible = {pid for pid, p in all_pages.items() if p["is_public"]}
        pages = [
            {"id": p["id"], "title": p["title"], "icon": p["icon"], "page_type": p["page_type"], "parent": public_parent(p, all_pages, visible)}
            for p in sorted(all_pages.values(), key=lambda p: (p["sort_order"], p["id"])) if p["id"] in visible
        ]
        return Response({
            "world": {"name": world.name, "description": world.description, "genre": world.genre},
            "books": books,
            "pages": pages,
        })


class PublicChapterView(PublicView):
    @extend_schema(responses=None)
    def get(self, request, token, chapter_pk):
        world = self.world(token)
        chapter = get_object_or_404(public_chapters(world).select_related("book"), pk=chapter_pk)
        siblings = list(public_chapters(world).filter(book=chapter.book).order_by("order", "id").values_list("id", flat=True))
        i = siblings.index(chapter.id)
        return Response({
            "id": chapter.id, "title": chapter.title, "book": {"id": chapter.book_id, "title": chapter.book.title},
            "content": strip_hidden_links(chapter.content, public_page_ids(world)),
            "word_count": chapter.word_count,
            "prev": siblings[i - 1] if i > 0 else None,
            "next": siblings[i + 1] if i + 1 < len(siblings) else None,
        })


def public_property(prop, titles):
    if prop.kind == PageProperty.Kind.PAGE:
        value = [prop.value] if isinstance(prop.value, int) else []
    elif prop.kind == PageProperty.Kind.PAGES:
        value = [v for v in prop.value if isinstance(v, int)] if isinstance(prop.value, list) else []
    else:
        return {"label": prop.label, "kind": prop.kind, "value": prop.value}
    return {"label": prop.label, "kind": prop.kind, "value": [{"id": v, "title": titles[v]} for v in value if v in titles]}


class PublicPageView(PublicView):
    @extend_schema(responses=None)
    def get(self, request, token, page_pk):
        world = self.world(token)
        page = get_object_or_404(Page.objects.filter(world=world, is_public=True).select_related("character"), pk=page_pk)
        titles = dict(Page.objects.filter(world=world, is_public=True).values_list("id", "title"))
        props = [public_property(p, titles) for p in page.properties.order_by("order", "id")]
        character = page.character
        return Response({
            "id": page.id, "title": page.title, "icon": page.icon, "page_type": page.page_type, "aliases": page.aliases,
            "has_cover": bool(page.cover), "updated_at": page.updated_at,
            "content": strip_hidden_links(page.content, set(titles)),
            "properties": [p for p in props if p["value"] not in (None, "", [], {})],
            "children": list(page.children.filter(is_public=True).order_by("sort_order", "id").values("id", "title", "icon")),
            "character": {
                "status": character.status, "birth_label": character.birth_label, "death_label": character.death_label,
                "has_portrait": bool(character.portrait),
            } if character else None,
        })


class PublicImageView(PublicView):
    """Covers and portraits of public items only."""

    @extend_schema(responses={(200, "image/*"): bytes})
    def get(self, request, token, kind, pk):
        world = self.world(token)
        if kind not in ("book-cover", "page-cover", "portrait"):
            raise NotFound("Невідомий тип зображення.")
        if kind == "book-cover":
            field = get_object_or_404(Book, world=world, is_public=True, pk=pk).cover
        elif kind == "page-cover":
            field = get_object_or_404(Page, world=world, is_public=True, pk=pk).cover
        else:
            page = get_object_or_404(Page.objects.select_related("character"), world=world, is_public=True, pk=pk)
            field = page.character.portrait if page.character else None
        return image_response(field, "Зображення немає.")
