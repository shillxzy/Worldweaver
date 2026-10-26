import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import Conflict
from apps.common.images import clear_image, image_response, replace_image
from apps.common.scoping import EDIT, MANAGE, VIEW, accessible_worlds, annotate_role, method_role, parse_id, require_role

from .docx_io import export_docx, parse_docx, blocks_to_document, choose_split_level, heading_levels, plan_chapters
from .documents import document_stats
from .models import Arc, Book, Chapter, ChapterVersion
from .serializers import (
    ArcSerializer,
    BookSerializer,
    ChapterListSerializer,
    ChapterSerializer,
    ChapterVersionDetailSerializer,
    ChapterVersionSerializer,
    DocxImportSerializer,
    DocxPreviewSerializer,
    ReorderSerializer,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def accessible_books(user, min_role=VIEW):
    return Book.objects.filter(world__in=accessible_worlds(user, min_role))


def safe_filename(title, fallback="worldweaver"):
    ascii_part = re.sub(r"[^A-Za-z0-9_-]+", "_", title).strip("_")[:60]
    return (ascii_part or fallback) + ".docx"


def docx_response(data, title):
    response = HttpResponse(data, content_type=DOCX_MIME)
    from urllib.parse import quote

    response["Content-Disposition"] = (
        f"attachment; filename=\"{safe_filename(title)}\"; filename*=UTF-8''{quote(title[:80] + '.docx')}"
    )
    return response


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = BookSerializer
    search_fields = ["title", "description", "genre"]
    ordering_fields = ["title", "created_at", "updated_at"]
    filterset_fields = ["world", "status"]

    def get_queryset(self):
        return (
            annotate_role(accessible_books(self.request.user), self.request.user, "world")
            .select_related("world", "world__owner__profile")
            .annotate(
                chapters_count=Count("chapters", distinct=True),
                done_chapters=Count("chapters", filter=Q(chapters__status=Chapter.Status.DONE), distinct=True),
                word_count=Sum("chapters__word_count"),
            )
            .order_by("-updated_at", "id")
        )

    # Deleting a book is structural (admins and the owner); exporting copies the whole manuscript (editors+).
    action_roles = {"destroy": MANAGE, "export": EDIT}

    def get_object(self):
        book = super().get_object()
        require_role(self.request.user, book.world, self.action_roles.get(self.action) or method_role(self.request))
        return book

    @extend_schema(responses={(200, DOCX_MIME): bytes})
    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        book = self.get_object()
        chapters = [(c.title, c.content) for c in book.chapters.order_by("order", "id")]
        return docx_response(export_docx(book.title, chapters), book.title)

    @extend_schema(request={"multipart/form-data": {"type": "object", "properties": {"cover": {"type": "string", "format": "binary"}}}}, responses=BookSerializer)
    @action(detail=True, methods=["get", "post", "delete"], parser_classes=[MultiPartParser], url_path="cover")
    def cover(self, request, pk=None):
        """Private cover image. The client crops it to 3:4 before upload; the server re-encodes it."""
        book = self.get_object()
        if request.method == "GET":
            return image_response(book.cover, "Обкладинку не завантажено.")
        if request.method == "DELETE":
            clear_image(book, "cover", ["updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        replace_image(book, "cover", request.FILES.get("cover"), 1600, ["updated_at"])
        return Response(self.get_serializer(self.get_queryset().get(pk=book.pk)).data)

    @extend_schema(responses=None)
    @action(detail=True, methods=["get"])
    def manuscript(self, request, pk=None):
        """Plain-text manuscript (used by the analysis pipeline and for preview)."""
        book = self.get_object()
        return Response({
            "book": book.id,
            "chapters": [
                {"id": c.id, "title": c.title, "order": c.order, "text": c.plain_text, "word_count": c.word_count}
                for c in book.chapters.order_by("order", "id")
            ],
        })


class ChapterViewSet(viewsets.ModelViewSet):
    queryset = Chapter.objects.none()  # schema introspection only; real data comes from get_queryset()
    search_fields = ["title", "plain_text"]
    filterset_fields = ["status"]

    # Version history and DOCX export are working tools of the writing team (editors+).
    action_roles = {"export": EDIT, "versions": EDIT, "version_detail": EDIT}

    def get_book(self):
        if not hasattr(self, "_book"):
            self._book = get_object_or_404(accessible_books(self.request.user).select_related("world"), pk=parse_id(self.kwargs["book_pk"]) or 0)
            require_role(self.request.user, self._book.world, self.action_roles.get(self.action) or method_role(self.request))
        return self._book

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.get_book()

    def get_queryset(self):
        qs = Chapter.objects.filter(book=self.get_book()).select_related("updated_by__profile")
        if self.action == "list":
            qs = qs.defer("content", "plain_text")
        return qs.order_by("order", "id")

    def get_serializer_class(self):
        return ChapterListSerializer if self.action == "list" else ChapterSerializer

    def perform_create(self, serializer):
        book = self.get_book()
        with transaction.atomic():
            last = Chapter.objects.select_for_update().filter(book=book).aggregate(m=Max("order"))["m"]
            serializer.validated_data.pop("base_revision", None)
            serializer.validated_data.pop("snapshot", None)
            serializer.save(book=book, order=0 if last is None else last + 1, updated_by=self.request.user)
            Book.objects.filter(pk=book.pk).update(updated_at=timezone.now())

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        with transaction.atomic():
            chapter = get_object_or_404(Chapter.objects.select_for_update(), pk=self.get_object().pk)
            serializer = self.get_serializer(chapter, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            base_revision = data.pop("base_revision", None)
            snapshot = data.pop("snapshot", False)
            if "content" in data:
                if base_revision is not None and base_revision != chapter.revision:
                    raise Conflict(
                        f"Розділ було змінено в іншому місці (ревізія {chapter.revision}, у вас {base_revision}). "
                        "Оновіть сторінку, щоб не втратити зміни."
                    )
                if data["content"] != chapter.content:
                    maybe_snapshot(chapter, ChapterVersion.Reason.MANUAL if snapshot else ChapterVersion.Reason.AUTOSAVE, force=snapshot)
                    data["revision"] = chapter.revision + 1
            serializer.save(updated_by=self.request.user)
            Book.objects.filter(pk=chapter.book_id).update(updated_at=timezone.now())
        return Response(serializer.data)

    @extend_schema(request=ReorderSerializer, responses=ChapterListSerializer(many=True))
    @action(detail=False, methods=["post"])
    def reorder(self, request, book_pk=None):
        serializer = ReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["order"]
        book = self.get_book()
        with transaction.atomic():
            chapters = {c.id: c for c in Chapter.objects.select_for_update().filter(book=book)}
            if set(ids) != set(chapters) or len(ids) != len(chapters):
                return Response(
                    {"error": {"code": "validation_error", "message": "Список має містити всі розділи книги рівно один раз.", "details": None}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            for position, chapter_id in enumerate(ids):
                chapters[chapter_id].order = position
            Chapter.objects.bulk_update(chapters.values(), ["order"])
        return Response(ChapterListSerializer(Chapter.objects.filter(book=book).order_by("order"), many=True).data)

    @extend_schema(responses={(200, DOCX_MIME): bytes})
    @action(detail=True, methods=["get"])
    def export(self, request, book_pk=None, pk=None):
        chapter = self.get_object()
        return docx_response(export_docx(None, [(chapter.title, chapter.content)]), chapter.title)

    @extend_schema(responses=ChapterVersionSerializer(many=True))
    @action(detail=True, methods=["get"])
    def versions(self, request, book_pk=None, pk=None):
        chapter = self.get_object()
        return Response(ChapterVersionSerializer(chapter.versions.select_related("author__profile").defer("content", "plain_text")[:100], many=True).data)

    @extend_schema(responses=ChapterVersionDetailSerializer)
    @action(detail=True, methods=["get"], url_path=r"versions/(?P<version_pk>\d{1,18})")
    def version_detail(self, request, book_pk=None, pk=None, version_pk=None):
        chapter = self.get_object()
        version = get_object_or_404(chapter.versions, pk=int(version_pk))
        return Response(ChapterVersionDetailSerializer(version).data)

    @extend_schema(request=None, responses=ChapterSerializer)
    @action(detail=True, methods=["post"], url_path=r"versions/(?P<version_pk>\d{1,18})/restore")
    def restore_version(self, request, book_pk=None, pk=None, version_pk=None):
        with transaction.atomic():
            chapter = get_object_or_404(Chapter.objects.select_for_update(), pk=self.get_object().pk)
            version = get_object_or_404(chapter.versions, pk=int(version_pk))
            maybe_snapshot(chapter, ChapterVersion.Reason.RESTORE, force=True)
            chapter.content = version.content
            chapter.plain_text = version.plain_text
            chapter.word_count = version.word_count
            chapter.revision += 1
            chapter.updated_by = request.user
            chapter.save()
        return Response(ChapterSerializer(chapter).data)


class ArcViewSet(viewsets.ModelViewSet):
    """Arcs (parts) of a book. Everyone in the world sees them; editors create and change them."""

    queryset = Arc.objects.none()  # schema introspection only
    serializer_class = ArcSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    get_book = ChapterViewSet.get_book
    action_roles = {}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.get_book()

    def get_queryset(self):
        return Arc.objects.filter(book=self.get_book())

    def perform_create(self, serializer):
        self._save(serializer, book=self.get_book())

    def perform_update(self, serializer):
        self._save(serializer)

    @transaction.atomic
    def _save(self, serializer, **extra):
        first = serializer.validated_data.pop("first_chapter", None)
        last = serializer.validated_data.pop("last_chapter", None)
        arc = serializer.save(**extra)
        if first is None:
            return
        chapters = list(Chapter.objects.select_for_update().filter(book=arc.book).order_by("order", "id"))
        ids = [c.id for c in chapters]
        if first not in ids or last not in ids:
            raise ValidationError({"first_chapter": "Розділ не належить цій книзі."})
        start, end = sorted((ids.index(first), ids.index(last)))
        inside = ids[start:end + 1]
        Chapter.objects.filter(arc=arc).exclude(id__in=inside).update(arc=None)
        Chapter.objects.filter(id__in=inside).update(arc=arc)


def maybe_snapshot(chapter, reason, force=False):
    """Store the chapter's current content as a version.

    Autosaves create at most one snapshot per WW_VERSION_INTERVAL_SECONDS; manual saves,
    restores and imports always snapshot. Old versions beyond the limit are pruned.
    """
    if not chapter.plain_text and not force:
        return None
    if not force:
        last = chapter.versions.order_by("-created_at").values_list("created_at", flat=True).first()
        if last and timezone.now() - last < timedelta(seconds=settings.WW_VERSION_INTERVAL_SECONDS):
            return None
    version = ChapterVersion.objects.create(
        chapter=chapter,
        revision=chapter.revision,
        title=chapter.title,
        content=chapter.content,
        plain_text=chapter.plain_text,
        word_count=chapter.word_count,
        reason=reason,
        author_id=chapter.updated_by_id,  # who wrote the text being preserved
    )
    stale = chapter.versions.order_by("-created_at", "-id").values_list("id", flat=True)[settings.WW_MAX_VERSIONS_PER_CHAPTER:]
    ChapterVersion.objects.filter(id__in=list(stale)).delete()
    return version


def _too_large():
    return Response(
        {"error": {"code": "validation_error", "message": "Файл завеликий.", "details": None}},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _default_title(data, upload):
    return (data.get("title") or upload.name.rsplit(".", 1)[0] or "Імпортований розділ")[:200]


class DocxPreviewView(APIView):
    """Dry run of the heading split: what chapters an import would create, without saving anything."""

    parser_classes = [MultiPartParser]

    @extend_schema(request={"multipart/form-data": DocxPreviewSerializer}, responses=None)
    def post(self, request):
        serializer = DocxPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        upload = data["file"]
        if upload.size > settings.WW_MAX_DOCX_BYTES:
            return _too_large()
        blocks = parse_docx(upload.read())
        level = data.get("split_level") or choose_split_level(blocks)
        chapters = []
        for part in plan_chapters(blocks, _default_title(data, upload), level):
            _, words = document_stats(blocks_to_document(part["blocks"]))
            chapters.append({"title": part["title"], "word_count": words, "merged": part["merged"], "lead_in": part.get("lead_in", False)})
        return Response({
            "levels": heading_levels(blocks),
            "split_level": level,
            "suggested_level": choose_split_level(blocks),
            "chapters": chapters,
        })


class DocxImportView(APIView):
    parser_classes = [MultiPartParser]

    @extend_schema(request={"multipart/form-data": DocxImportSerializer}, responses=ChapterListSerializer(many=True))
    def post(self, request):
        serializer = DocxImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        book = get_object_or_404(accessible_books(request.user), pk=parse_id(data["book"]) or 0)
        require_role(request.user, book.world, EDIT)
        upload = data["file"]
        if upload.size > settings.WW_MAX_DOCX_BYTES:
            return _too_large()
        blocks = parse_docx(upload.read())
        default_title = _default_title(data, upload)

        with transaction.atomic():
            if data["mode"] == "replace_chapter":
                chapter = get_object_or_404(Chapter.objects.select_for_update().filter(book=book), pk=parse_id(data.get("chapter")) or 0)
                maybe_snapshot(chapter, ChapterVersion.Reason.IMPORT, force=True)
                chapter.content = blocks_to_document(blocks)
                chapter.plain_text, chapter.word_count = document_stats(chapter.content)
                chapter.revision += 1
                chapter.updated_by = request.user
                chapter.save()
                created = [chapter]
            else:
                if data["mode"] == "split_headings":
                    parts = [
                        (part["title"], blocks_to_document(part["blocks"]))
                        for part in plan_chapters(blocks, default_title, data.get("split_level"))
                    ]
                else:
                    parts = [(default_title, blocks_to_document(blocks))]
                last = Chapter.objects.select_for_update().filter(book=book).aggregate(m=Max("order"))["m"]
                start = 0 if last is None else last + 1
                created = []
                for offset, (title, content) in enumerate(parts):
                    text, words = document_stats(content)
                    created.append(Chapter.objects.create(
                        book=book, title=title, order=start + offset, content=content, plain_text=text, word_count=words,
                        updated_by=request.user,
                    ))
            Book.objects.filter(pk=book.pk).update(updated_at=timezone.now())
        return Response(ChapterListSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


class GlobalSearchView(APIView):
    @extend_schema(parameters=[OpenApiParameter("q", str, required=True)], responses=None)
    def get(self, request):
        from apps.worlds.views import search_world

        query = request.query_params.get("q", "")
        results = []
        if len(query.strip()) >= 2:
            for book in accessible_books(request.user).filter(Q(title__icontains=query.strip()) | Q(description__icontains=query.strip()))[:20]:
                results.append({"type": "book", "id": book.id, "title": book.title, "snippet": book.description[:160], "world": book.world_id})
            for world in accessible_worlds(request.user):
                for item in search_world(world, query, limit=8)["results"]:
                    item["world"] = world.id
                    results.append(item)
        return Response({"query": query.strip()[:100], "results": results[:80]})
