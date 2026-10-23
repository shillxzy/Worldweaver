import math
import re

from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.images import clear_image, image_response, replace_image
from apps.common.scoping import WorldScopedMixin, owned_world_or_404

from .models import (
    Character,
    EventParticipant,
    Faction,
    FactionMembership,
    GraphLayout,
    LoreEntry,
    Relationship,
    TimelineDependency,
    TimelineEvent,
    World,
)
from .serializers import (
    CharacterSerializer,
    DependencySerializer,
    FactionSerializer,
    LoreEntrySerializer,
    MembershipSerializer,
    RelationshipSerializer,
    TimelineEventSerializer,
    WorldSerializer,
)


class WorldViewSet(viewsets.ModelViewSet):
    queryset = World.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = WorldSerializer
    search_fields = ["name", "description", "genre"]
    ordering_fields = ["name", "created_at", "updated_at"]
    filterset_fields = ["genre"]

    def get_queryset(self):
        return World.objects.filter(owner=self.request.user).annotate(
            characters_count=Count("characters", distinct=True),
            factions_count=Count("factions", distinct=True),
            lore_count=Count("lore_entries", distinct=True),
            events_count=Count("events", distinct=True),
            books_count=Count("books", distinct=True),
        ).order_by("-updated_at", "id")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class CharacterViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = Character.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = CharacterSerializer
    search_fields = ["name", "aliases_text", "summary", "biography", "abilities", "notes"]
    ordering_fields = ["name", "created_at", "updated_at", "birth_key"]
    filterset_fields = ["status"]

    def perform_create(self, serializer):
        # Every structured record gets an encyclopedia page (the page is the main editing surface).
        _ensure_page(serializer.save(world=self.get_world()), "character")

    def get_queryset(self):
        qs = Character.objects.filter(world=self.get_world()).select_related("page").prefetch_related(
            Prefetch("memberships", queryset=FactionMembership.objects.select_related("faction"))
        )
        faction = self.request.query_params.get("faction")
        if faction and faction.isdigit():
            qs = qs.filter(memberships__faction_id=int(faction)).distinct()
        return qs

    @extend_schema(request={"multipart/form-data": {"type": "object", "properties": {"portrait": {"type": "string", "format": "binary"}}}}, responses=CharacterSerializer)
    @action(detail=True, methods=["get", "post", "delete"], parser_classes=[MultiPartParser], url_path="portrait")
    def portrait(self, request, world_pk=None, pk=None):
        character = self.get_object()
        if request.method == "GET":
            return image_response(character.portrait, "Портрет не завантажено.")
        if request.method == "DELETE":
            clear_image(character, "portrait", ["updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        replace_image(character, "portrait", request.FILES.get("portrait"), 1024, ["updated_at"])
        return Response(self.get_serializer(character).data)


def _ensure_page(record, kind):
    from apps.pages.services import page_for_record

    page_for_record(record, kind)


class FactionViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = Faction.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = FactionSerializer
    search_fields = ["name", "description", "goals", "ideology"]
    ordering_fields = ["name", "created_at"]

    def perform_create(self, serializer):
        # Every structured record gets an encyclopedia page (the page is the main editing surface).
        _ensure_page(serializer.save(world=self.get_world()), "faction")

    def get_queryset(self):
        return (
            Faction.objects.filter(world=self.get_world()).select_related("page")
            .annotate(members_count=Count("memberships__character", distinct=True))
            .order_by("name", "id")
        )


class MembershipViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = FactionMembership.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = MembershipSerializer
    filterset_fields = ["character", "faction"]

    def get_queryset(self):
        return FactionMembership.objects.filter(character__world=self.get_world()).select_related("character", "faction")

    def perform_create(self, serializer):
        serializer.save()


class LoreEntryViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = LoreEntry.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = LoreEntrySerializer
    search_fields = ["title", "content", "custom_category", "tags__name"]
    ordering_fields = ["title", "created_at", "updated_at", "category"]
    filterset_fields = ["category"]

    def perform_create(self, serializer):
        # Every structured record gets an encyclopedia page (the page is the main editing surface).
        _ensure_page(serializer.save(world=self.get_world()), "lore")

    def get_queryset(self):
        qs = LoreEntry.objects.filter(world=self.get_world()).prefetch_related("tags", "related_characters", "related_factions")
        tag = self.request.query_params.get("tag")
        if tag:
            qs = qs.filter(tags__name=tag.strip().lower())
        return qs.distinct()


class TimelineEventViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = TimelineEvent.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = TimelineEventSerializer
    search_fields = ["title", "description", "start_label"]
    ordering_fields = ["start_key", "sort_order", "created_at"]
    filterset_fields = ["precision"]

    def get_queryset(self):
        qs = TimelineEvent.objects.filter(world=self.get_world()).prefetch_related(
            Prefetch("participants", queryset=EventParticipant.objects.select_related("character")),
            "factions",
            "lore_entries",
            "chapters",
        )
        character = self.request.query_params.get("character")
        if character and character.isdigit():
            qs = qs.filter(participants__character_id=int(character)).distinct()
        return qs.order_by(F("start_key").asc(nulls_last=True), "sort_order", "id")


class DependencyViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = TimelineDependency.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = DependencySerializer
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return TimelineDependency.objects.filter(world=self.get_world()).select_related("before", "after")

    def perform_create(self, serializer):
        with transaction.atomic():
            serializer.save(world=self.get_world())


RELATION_SIDES = [f"{side}_{t}" for side in ("source", "target") for t in Relationship.ENTITY_TYPES]


class RelationshipViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = Relationship.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = RelationshipSerializer
    filterset_fields = ["kind"]
    search_fields = ["description"]

    def get_queryset(self):
        qs = Relationship.objects.filter(world=self.get_world()).select_related(*RELATION_SIDES)
        entity_type = self.request.query_params.get("entity_type")
        entity_id = self.request.query_params.get("entity_id")
        if entity_type in Relationship.ENTITY_TYPES and entity_id and entity_id.isdigit():
            key = int(entity_id)
            qs = qs.filter(Q(**{f"source_{entity_type}_id": key}) | Q(**{f"target_{entity_type}_id": key}))
        return qs


class WorldSearchView(APIView):
    """Full-text-ish search inside one world (names, aliases, tags, content)."""

    @extend_schema(parameters=[OpenApiParameter("q", str, required=True)], responses=None)
    def get(self, request, world_pk):
        world = owned_world_or_404(request.user, world_pk)
        return Response(search_world(world, request.query_params.get("q", "")))


def search_world(world, query, limit=20):
    query = (query or "").strip()[:100]
    if len(query) < 2:
        return {"query": query, "results": []}
    results = []
    from apps.pages.models import Page

    q_lower = query.lower()
    for page in Page.objects.filter(world=world).filter(
        Q(title__icontains=query) | Q(aliases_text__icontains=query) | Q(plain_text__icontains=query)
    ).order_by("title")[: limit * 2]:
        idx = page.plain_text.lower().find(q_lower)
        snippet = page.plain_text[max(0, idx - 50): idx + 110] if idx >= 0 else page.plain_text[:160]
        results.append({"type": "page", "id": page.id, "title": page.title, "snippet": snippet, "page_type": page.page_type, "icon": page.icon})
    for ev in TimelineEvent.objects.filter(world=world).filter(Q(title__icontains=query) | Q(description__icontains=query))[:limit]:
        results.append({"type": "event", "id": ev.id, "title": ev.title, "snippet": ev.description[:160]})
    from apps.books.models import Chapter

    for ch in Chapter.objects.filter(book__world=world).filter(Q(title__icontains=query) | Q(plain_text__icontains=query)).select_related("book")[:limit]:
        idx = ch.plain_text.lower().find(query.lower())
        snippet = ch.plain_text[max(0, idx - 60): idx + 100] if idx >= 0 else ""
        results.append({"type": "chapter", "id": ch.id, "book": ch.book_id, "title": f"{ch.book.title} — {ch.title}", "snippet": snippet})
    return {"query": query, "results": results}


GRAPH_KEY_RE = re.compile(r"^(character|faction):\d{1,18}$")


class GraphLayoutView(APIView):
    """Saved node positions for the world graphs (``factions`` / ``relations``)."""

    @extend_schema(responses=None)
    def get(self, request, world_pk, view):
        world = owned_world_or_404(request.user, world_pk)
        layout = GraphLayout.objects.filter(world=world, view=_graph_view(view)).first()
        return Response({"view": view, "positions": layout.positions if layout else {}})

    @extend_schema(request=None, responses=None)
    def put(self, request, world_pk, view):
        world = owned_world_or_404(request.user, world_pk)
        positions = request.data.get("positions") if isinstance(request.data, dict) else None
        if not isinstance(positions, dict) or len(positions) > 2000:
            raise ValidationError({"positions": "Очікується обʼєкт із не більше ніж 2000 вузлів."})
        clean = {}
        for key, value in positions.items():
            if not isinstance(key, str) or not GRAPH_KEY_RE.match(key):
                raise ValidationError({"positions": f"Некоректний ключ вузла: {str(key)[:40]}"})
            if (not isinstance(value, list) or len(value) != 2
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= 1e6 for v in value)):
                raise ValidationError({"positions": f"Некоректна позиція для {key}."})
            clean[key] = [round(float(value[0]), 1), round(float(value[1]), 1)]
        GraphLayout.objects.update_or_create(world=world, view=_graph_view(view), defaults={"positions": clean})
        return Response({"view": view, "positions": clean})


def _graph_view(view):
    if view not in GraphLayout.View.values:
        raise NotFound("Невідомий вид графа.")
    return view
