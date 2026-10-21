import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from PIL import Image, UnidentifiedImageError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.scoping import WorldScopedMixin, owned_world_or_404

from .models import (
    Character,
    EventParticipant,
    Faction,
    FactionMembership,
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

    def get_queryset(self):
        qs = Character.objects.filter(world=self.get_world()).prefetch_related(
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
            if not character.portrait:
                raise NotFound("Портрет не завантажено.")
            # Portraits are re-encoded to <=1024px on upload, so reading them fully is cheap and
            # avoids holding a file handle open (Windows locks open files).
            with character.portrait.open("rb") as fh:
                response = HttpResponse(fh.read(), content_type="image/" + _image_ext(character.portrait.name))
            response["Cache-Control"] = "private, max-age=300"
            response["X-Content-Type-Options"] = "nosniff"
            return response
        if request.method == "DELETE":
            if character.portrait:
                character.portrait.delete(save=False)
            character.portrait = None
            character.save(update_fields=["portrait", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)
        upload = request.FILES.get("portrait")
        content, ext = validate_portrait(upload)
        old = character.portrait.name if character.portrait else None
        character.portrait.save(f"{uuid.uuid4().hex}.{ext}", ContentFile(content), save=False)
        character.save(update_fields=["portrait", "updated_at"])
        if old:
            character.portrait.storage.delete(old)
        return Response(self.get_serializer(character).data)


def _image_ext(name):
    ext = name.rsplit(".", 1)[-1].lower()
    return {"jpg": "jpeg"}.get(ext, ext)


ALLOWED_IMAGE_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def validate_portrait(upload):
    """Validate an uploaded image by content (not by name) and re-encode it.

    Re-encoding strips metadata and any trailing payload; the original filename is never used.
    """
    if upload is None:
        raise ValidationError({"portrait": "Файл не передано."})
    if upload.size > settings.WW_MAX_PORTRAIT_BYTES:
        raise ValidationError({"portrait": f"Файл завеликий (максимум {settings.WW_MAX_PORTRAIT_BYTES // 1024 // 1024} МБ)."})
    try:
        with Image.open(upload) as probe:
            probe.verify()
        upload.seek(0)
        with Image.open(upload) as img:
            fmt = img.format
            if fmt not in ALLOWED_IMAGE_FORMATS:
                raise ValidationError({"portrait": "Дозволені формати: JPEG, PNG, WEBP."})
            if img.width * img.height > 40_000_000:
                raise ValidationError({"portrait": "Зображення має завелику роздільну здатність."})
            img.thumbnail((1024, 1024))
            if fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            from io import BytesIO

            buffer = BytesIO()
            img.save(buffer, format=fmt)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError({"portrait": "Файл не є коректним зображенням."}) from exc
    return buffer.getvalue(), ALLOWED_IMAGE_FORMATS[fmt]


class FactionViewSet(WorldScopedMixin, viewsets.ModelViewSet):
    queryset = Faction.objects.none()  # schema introspection only; real data comes from get_queryset()
    serializer_class = FactionSerializer
    search_fields = ["name", "description", "goals", "ideology"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        return (
            Faction.objects.filter(world=self.get_world())
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
    for c in Character.objects.filter(world=world).filter(
        Q(name__icontains=query) | Q(aliases_text__icontains=query) | Q(summary__icontains=query) | Q(biography__icontains=query)
    )[:limit]:
        results.append({"type": "character", "id": c.id, "title": c.name, "snippet": c.summary[:160]})
    for f in Faction.objects.filter(world=world).filter(Q(name__icontains=query) | Q(description__icontains=query))[:limit]:
        results.append({"type": "faction", "id": f.id, "title": f.name, "snippet": f.description[:160]})
    for e in LoreEntry.objects.filter(world=world).filter(
        Q(title__icontains=query) | Q(content__icontains=query) | Q(tags__name__icontains=query.lower())
    ).distinct()[:limit]:
        results.append({"type": "lore", "id": e.id, "title": e.title, "snippet": e.content[:160], "category": e.category})
    for ev in TimelineEvent.objects.filter(world=world).filter(Q(title__icontains=query) | Q(description__icontains=query))[:limit]:
        results.append({"type": "event", "id": ev.id, "title": ev.title, "snippet": ev.description[:160]})
    from apps.books.models import Chapter

    for ch in Chapter.objects.filter(book__world=world).filter(Q(title__icontains=query) | Q(plain_text__icontains=query)).select_related("book")[:limit]:
        idx = ch.plain_text.lower().find(query.lower())
        snippet = ch.plain_text[max(0, idx - 60): idx + 100] if idx >= 0 else ""
        results.append({"type": "chapter", "id": ch.id, "book": ch.book_id, "title": f"{ch.book.title} — {ch.title}", "snippet": snippet})
    return {"query": query, "results": results}
