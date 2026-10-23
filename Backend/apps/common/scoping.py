"""Access scoping helpers.

Data isolation is enforced at the queryset level: every lookup of a world (or of an object
below it) is limited to worlds the user owns or is a member of. Worlds without access are
indistinguishable from missing ones (404), so ids of foreign objects do not leak. Inside an
accessible world each request also needs a minimum role (403 when the role is too low):
reading needs ``VIEW``, changing content ``EDIT`` (see docs/COLLABORATION.md).
"""
from django.db.models import Case, CharField, OuterRef, Q, Subquery, Value, When
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import SAFE_METHODS

from apps.collab.models import RANK, Role, WorldMember
from apps.worlds.models import World

MAX_DB_ID = 2**63 - 1

# Minimum roles, by purpose.
VIEW, COMMENT, EDIT, MANAGE, OWN = Role.VIEWER, Role.COMMENTER, Role.EDITOR, Role.ADMIN, Role.OWNER

DENIED = {
    COMMENT: "Коментувати можуть коментатори, редактори, адміністратори та власник.",
    EDIT: "Ваша роль у цьому проєкті дозволяє лише читати.",
    MANAGE: "Керувати учасниками можуть лише адміністратори та власник.",
    OWN: "Це може зробити лише власник проєкту.",
}


def parse_id(value):
    """Return a positive int id or None (avoids DB errors on huge/invalid ids)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= MAX_DB_ID else None


def accessible_worlds(user, min_role=VIEW):
    """Worlds where ``user`` has at least ``min_role`` (owners have every role)."""
    if not user.is_authenticated:
        return World.objects.none()
    member_roles = [r for r, rank in RANK.items() if r != OWN and rank >= RANK[min_role]]
    shared = WorldMember.objects.filter(user=user, role__in=member_roles).values("world_id")
    return World.objects.filter(Q(owner=user) | Q(pk__in=shared))


def annotate_role(qs, user, world_path=""):
    """Add ``my_role`` to each row of a world (``world_path=""``) or of objects below a world."""
    prefix = f"{world_path}__" if world_path else ""
    member = WorldMember.objects.filter(world_id=OuterRef(f"{world_path}_id" if world_path else "pk"), user_id=user.pk)
    return qs.annotate(my_role=Case(
        When(**{f"{prefix}owner_id": user.pk}, then=Value(OWN.value)),
        default=Subquery(member.values("role")[:1]),
        output_field=CharField(),
    ))


def world_role(user, world):
    """The user's role in ``world`` or None. Cached on the world instance for the request."""
    cache = world.__dict__.setdefault("_roles", {})
    if user.pk not in cache:
        if user.is_authenticated and world.owner_id == user.pk:
            cache[user.pk] = OWN
        else:
            cache[user.pk] = WorldMember.objects.filter(world=world, user_id=user.pk).values_list("role", flat=True).first()
    return cache[user.pk]


def has_role(user, world, min_role):
    role = world_role(user, world)
    return role is not None and RANK[role] >= RANK[min_role]


def require_role(user, world, min_role):
    """404 when the user has no access to the world at all, 403 when the role is too low."""
    role = world_role(user, world)
    if role is None:
        raise NotFound("Не знайдено.")
    if RANK[role] < RANK[min_role]:
        raise PermissionDenied(DENIED.get(min_role, DENIED[EDIT]))
    return role


def world_or_404(user, world_id, min_role=VIEW):
    world = get_object_or_404(accessible_worlds(user), pk=parse_id(world_id) or 0)
    require_role(user, world, min_role)
    return world


def method_role(request):
    """Default rule: reading needs VIEW, any change needs EDIT."""
    return VIEW if request.method in SAFE_METHODS else EDIT


class WorldScopedMixin:
    """For viewsets nested under ``/worlds/<world_pk>/...``.

    ``action_roles`` maps an action name to its minimum role; other actions follow ``method_role``.
    """

    action_roles = {}

    def required_role(self):
        return self.action_roles.get(self.action) or method_role(self.request)

    def get_world(self):
        if not hasattr(self, "_world"):
            self._world = world_or_404(self.request.user, self.kwargs.get("world_pk"), self.required_role())
        return self._world

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.kwargs.get("world_pk") is not None:
            self.get_world()  # check access before any work (also for actions that never touch the queryset)

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
