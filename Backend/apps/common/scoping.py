"""Ownership scoping helpers.

Data isolation is enforced at the queryset level: every lookup of a world (or of an
object below it) is filtered by ``owner=request.user``. Objects of other users are
indistinguishable from missing ones (404), so ids of foreign objects do not leak.
"""
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from apps.worlds.models import World

MAX_DB_ID = 2**63 - 1


def parse_id(value):
    """Return a positive int id or None (avoids DB errors on huge/invalid ids)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= MAX_DB_ID else None


def owned_world_or_404(user, world_id):
    return get_object_or_404(World.objects.filter(owner=user), pk=parse_id(world_id) or 0)


class WorldScopedMixin:
    """For viewsets nested under ``/worlds/<world_pk>/...``."""

    def get_world(self):
        if not hasattr(self, "_world"):
            self._world = owned_world_or_404(self.request.user, self.kwargs.get("world_pk"))
        return self._world

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.kwargs.get("world_pk") is not None:
            context["world"] = self.get_world()
        return context

    def perform_create(self, serializer):
        serializer.save(world=self.get_world())


class WorldRelatedField(serializers.PrimaryKeyRelatedField):
    """PK field that only accepts objects belonging to ``context['world']``.

    ``world_path`` is the ORM path from the related model to its World
    (``"world"`` for most models, ``"book__world"`` for chapters).
    """

    default_error_messages = {
        **serializers.PrimaryKeyRelatedField.default_error_messages,
        "does_not_exist": "Обʼєкт {pk_value} не існує в цьому світі.",
        "incorrect_type": "Очікувався числовий ідентифікатор.",
    }

    def __init__(self, model, world_path="world", **kwargs):
        self.model = model
        self.world_path = world_path
        kwargs.setdefault("queryset", model.objects.all())
        super().__init__(**kwargs)

    def get_queryset(self):
        world = self.context.get("world")
        if world is None:
            return self.model.objects.none()
        return self.model.objects.filter(**{self.world_path: world})

    def to_internal_value(self, data):
        if isinstance(data, bool) or parse_id(data) is None:
            self.fail("incorrect_type", data_type=type(data).__name__)
        return super().to_internal_value(data)
