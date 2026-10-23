from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analysis.engine.mentions import MentionMatcher
from apps.books.models import Chapter
from apps.common.exceptions import Conflict
from apps.common.images import clear_image, image_response, replace_image
from apps.common.scoping import WorldScopedMixin, accessible_worlds, parse_id
from apps.worlds.models import Character, Faction, LoreEntry

from .models import Page, PageLink, PageProperty, PageTemplate
from .serializers import (
    MoveSerializer,
    PageCreateSerializer,
    PageListSerializer,
    PageSerializer,
    PropertySerializer,
    TemplateSerializer,
)
from .services import create_page, delete_page, fuzzy_page_ids, move_page, page_for_record, rebuild_links, sync_entity
from .templates import BUILTIN_TEMPLATES


def _with_children_flag(qs):
    return qs.annotate(has_children=Exists(Page.objects.filter(parent=OuterRef("pk"))))


def page_detail(page, context):
    """Full page payload: content, properties, breadcrumbs, children, backlinks, outgoing/broken links."""
    data = PageSerializer(page, context=context).data
    crumbs, cur = [], page.parent
    seen = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        crumbs.append({"id": cur.id, "title": cur.title, "icon": cur.icon})
        cur = cur.parent
    data["breadcrumbs"] = crumbs[::-1]
    data["children"] = PageListSerializer(_with_children_flag(page.children.all()), many=True).data
    backlinks = (
        PageLink.objects.filter(target=page).exclude(source=page).select_related("source")
        .order_by("source__title").distinct()
    )
    seen_sources = {}
    for link in backlinks:
        seen_sources.setdefault(link.source_id, {"id": link.source_id, "title": link.source.title, "icon": link.source.icon, "page_type": link.source.page_type, "origins": []})
        seen_sources[link.source_id]["origins"].append(link.origin)
    data["backlinks"] = list(seen_sources.values())
    data["links"] = [
        {"target_ref": link.target_ref, "origin": link.origin, "broken": link.target_id is None,
         "title": link.target.title if link.target_id else None}
        for link in page.outgoing_links.select_related("target").order_by("id")
    ]
    return data


class PageViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = Page.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = PageListSerializer
    search_fields = ["title", "aliases_text", "plain_text"]
    ordering_fields = ["title", "updated_at", "sort_order"]
    filterset_fields = ["page_type"]

    def get_queryset(self):
        qs = Page.objects.filter(world=self.get_world()).select_related("parent")
        parent = self.request.query_params.get("parent")
        if parent == "root":
            qs = qs.filter(parent__isnull=True)
        elif parent and parse_id(parent):
            qs = qs.filter(parent_id=parse_id(parent))
        return _with_children_flag(qs)

    def get_serializer_class(self):
        if self.action in ("retrieve", "partial_update", "update"):
            return PageSerializer
        return PageListSerializer

    @extend_schema(request=PageCreateSerializer, responses=PageSerializer)
    def create(self, request, *args, **kwargs):
        world = self.get_world()
        serializer = PageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        parent = None
        if data.get("parent"):
            parent = get_object_or_404(Page.objects.filter(world=world), pk=data["parent"])
        user_template = None
        template = data.get("template") or ""
        if data.get("user_template"):
            user_template = get_object_or_404(
                PageTemplate.objects.filter(owner=request.user).filter(Q(world=world) | Q(world__isnull=True)), pk=data["user_template"]
            )
        page = create_page(world, data.get("title", ""), parent, template or None, user_template, data.get("page_type"), data.get("icon"))
        Page.objects.filter(pk=page.pk).update(updated_by=request.user)
        page.updated_by = request.user
        rebuild_links(page, PageLink.Origin.CONTENT)
        return Response(page_detail(page, self.get_serializer_context()), status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        return Response(page_detail(self.get_object(), self.get_serializer_context()))

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        with transaction.atomic():
            page = get_object_or_404(Page.objects.select_for_update(), pk=self.get_object().pk)
            serializer = PageSerializer(page, data=request.data, partial=partial, context=self.get_serializer_context())
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            base_revision = data.pop("base_revision", None)
            if "content" in data:
                if base_revision is not None and base_revision != page.revision:
                    raise Conflict(f"Сторінку змінено в іншому місці (ревізія {page.revision}, у вас {base_revision}).")
                if data["content"] != page.content:
                    data["revision"] = page.revision + 1
            page = serializer.save(updated_by=request.user)
            if "content" in data:
                rebuild_links(page, PageLink.Origin.CONTENT)
            sync_entity(page)
        return Response(page_detail(page, self.get_serializer_context()))

    def destroy(self, request, *args, **kwargs):
        page = self.get_object()
        mode = request.query_params.get("children")
        count = delete_page(page, mode if mode in ("lift", "delete") else None)
        return Response({"deleted": count}, status=status.HTTP_200_OK)

    @extend_schema(request=MoveSerializer, responses=PageSerializer)
    @action(detail=True, methods=["post"])
    def move(self, request, world_pk=None, pk=None):
        page = self.get_object()
        serializer = MoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent_id = serializer.validated_data["parent"]
        parent = get_object_or_404(Page.objects.filter(world=self.get_world()), pk=parent_id) if parent_id else None
        move_page(page, parent, serializer.validated_data.get("position"))
        return Response(PageListSerializer(_with_children_flag(Page.objects.filter(pk=page.pk)).get()).data)

    @extend_schema(parameters=[OpenApiParameter("q", str)], responses=PageListSerializer(many=True))
    @action(detail=False, methods=["get"])
    def lookup(self, request, world_pk=None):
        """Fast title/alias search for the link picker (no content search)."""
        q = request.query_params.get("q", "").strip()[:100]
        qs = self.get_queryset()
        if not q:
            return Response(PageListSerializer(qs.order_by("title")[:20], many=True).data)
        exact = list(qs.filter(Q(title__icontains=q) | Q(aliases_text__icontains=q)).order_by("title")[:20])
        if len(exact) < 20:
            # Inflected selections ("Джонатаном Андерсоном") still find "Джонатан Андерсон".
            ids = fuzzy_page_ids(qs.exclude(pk__in=[p.pk for p in exact]), q, 20 - len(exact))
            exact += sorted(qs.filter(pk__in=ids), key=lambda p: ids.index(p.pk))
        return Response(PageListSerializer(exact, many=True).data)

    @extend_schema(parameters=[OpenApiParameter("type", str), OpenApiParameter("id", int)], responses=PageListSerializer)
    @action(detail=False, methods=["get"], url_path="by-entity")
    def by_entity(self, request, world_pk=None):
        """The page of a structured record (created on demand for records made outside the encyclopedia)."""
        world = self.get_world()
        kind = request.query_params.get("type")
        record_id = parse_id(request.query_params.get("id")) or 0
        model = {"character": Character, "faction": Faction, "lore": LoreEntry}.get(kind)
        if model is None:
            raise NotFound("Невідомий тип запису.")
        record = get_object_or_404(model.objects.filter(world=world), pk=record_id)
        page = page_for_record(record, kind)
        return Response(PageListSerializer(_with_children_flag(Page.objects.filter(pk=page.pk)).get()).data)

    @extend_schema(request=None, responses=TemplateSerializer)
    @action(detail=True, methods=["post"], url_path="save-as-template")
    def save_as_template(self, request, world_pk=None, pk=None):
        page = self.get_object()
        name = str(request.data.get("name") or page.title).strip()[:80]
        template = PageTemplate.objects.create(
            owner=request.user, world=page.world, name=name, icon=page.icon, page_type=page.page_type,
            content=page.content, properties=[{"label": p.label, "kind": p.kind} for p in page.properties.all()],
        )
        return Response(TemplateSerializer(template).data, status=status.HTTP_201_CREATED)

    @extend_schema(request={"multipart/form-data": {"type": "object", "properties": {"cover": {"type": "string", "format": "binary"}}}}, responses=None)
    @action(detail=True, methods=["get", "post", "delete"], parser_classes=[MultiPartParser], url_path="cover")
    def cover(self, request, world_pk=None, pk=None):
        page = self.get_object()
        if request.method == "GET":
            return image_response(page.cover, "Обкладинку не завантажено.")
        if request.method == "DELETE":
            clear_image(page, "cover", ["updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        replace_image(page, "cover", request.FILES.get("cover"), 1800, ["updated_at"])
        return Response(page_detail(page, self.get_serializer_context()))


class PropertyViewSet(WorldScopedMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = PageProperty.objects.none()  # schema introspection only
    serializer_class = PropertySerializer
    http_method_names = ["post", "patch", "delete", "options"]

    def get_page(self):
        if not hasattr(self, "_page"):
            self._page = get_object_or_404(Page.objects.filter(world=self.get_world()), pk=parse_id(self.kwargs["page_pk"]) or 0)
        return self._page

    def get_queryset(self):
        return PageProperty.objects.filter(page=self.get_page())

    def perform_create(self, serializer):
        page = self.get_page()
        if page.properties.count() >= 60:
            raise ValidationError("Забагато властивостей на сторінці.")
        last = page.properties.order_by("-order").values_list("order", flat=True).first()
        serializer.save(page=page, order=(last or 0) + 1)
        self._touch(page)

    def perform_update(self, serializer):
        serializer.save()
        self._touch(self.get_page())

    def perform_destroy(self, instance):
        instance.delete()
        self._touch(self.get_page())

    @staticmethod
    def _touch(page):
        rebuild_links(page, PageLink.Origin.PROPERTY)
        page.save(update_fields=["updated_at"])

    @extend_schema(request=None, responses=PropertySerializer(many=True))
    @action(detail=False, methods=["post"])
    def reorder(self, request, world_pk=None, page_pk=None):
        ids = request.data.get("order")
        props = {p.id: p for p in self.get_queryset()}
        if not isinstance(ids, list) or set(ids) != set(props) or len(ids) != len(props):
            raise ValidationError({"order": "Список має містити всі властивості сторінки рівно один раз."})
        for index, pid in enumerate(ids):
            props[pid].order = index
        PageProperty.objects.bulk_update(props.values(), ["order"])
        return Response(PropertySerializer(self.get_queryset(), many=True).data)


class TemplateListView(APIView):
    """Built-in templates plus the user's own (global or for the given world)."""

    @extend_schema(parameters=[OpenApiParameter("world", int)], responses=None)
    def get(self, request):
        builtin = [
            {"key": key, "builtin": True, "name": spec["name"], "icon": spec["icon"], "page_type": spec["page_type"],
             "properties": spec["properties"], "id": None, "world": None}
            for key, spec in BUILTIN_TEMPLATES.items()
        ]
        world_id = parse_id(request.query_params.get("world"))
        own = PageTemplate.objects.filter(owner=request.user)
        own = own.filter(Q(world__isnull=True) | Q(world_id=world_id)) if world_id else own.filter(world__isnull=True)
        return Response(builtin + TemplateSerializer(own, many=True).data)


class TemplateDeleteView(APIView):
    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        get_object_or_404(PageTemplate.objects.filter(owner=request.user), pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RelevantPagesView(APIView):
    """Encyclopedia pages mentioned in a chapter (titles and aliases, with Ukrainian inflection)."""

    @extend_schema(responses=None)
    def get(self, request, book_pk, chapter_pk):
        chapter = get_object_or_404(
            Chapter.objects.select_related("book__world").filter(book__world__in=accessible_worlds(request.user), book_id=book_pk), pk=chapter_pk
        )
        pages = list(Page.objects.filter(world=chapter.book.world).only("id", "title", "icon", "page_type", "aliases"))
        matcher = MentionMatcher([(p.id, [p.title, *p.aliases]) for p in pages])
        counts = {}
        for mention in matcher.find(chapter.plain_text):
            counts[mention.entity_id] = counts.get(mention.entity_id, 0) + 1
        by_id = {p.id: p for p in pages}
        result = [
            {"id": pid, "title": by_id[pid].title, "icon": by_id[pid].icon, "page_type": by_id[pid].page_type, "mentions": n}
            for pid, n in sorted(counts.items(), key=lambda x: -x[1])
        ]
        return Response({"chapter": chapter.id, "pages": result})
