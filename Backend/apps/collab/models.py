"""Co-writing: who may do what in a world (the shared unit: a world with all its books).

The owner is ``World.owner``; everybody else is a ``WorldMember`` with one role. Roles are
ordered — each one includes everything the lower roles may do (see ``RANK`` and docs/COLLABORATION.md).
"""
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.worlds.models import World


class Role(models.TextChoices):
    OWNER = "owner", "Власник"
    ADMIN = "admin", "Адміністратор"
    EDITOR = "editor", "Редактор"
    COMMENTER = "commenter", "Коментатор"
    VIEWER = "viewer", "Читач"


RANK = {Role.VIEWER: 10, Role.COMMENTER: 20, Role.EDITOR: 30, Role.ADMIN: 40, Role.OWNER: 50}
MEMBER_ROLES = [(r.value, r.label) for r in Role if r != Role.OWNER]
# Links can be forwarded, so they never grant more than editing; admins are appointed by the owner.
LINK_ROLES = [Role.VIEWER, Role.COMMENTER, Role.EDITOR]


def new_token():
    return secrets.token_urlsafe(24)


class WorldMember(models.Model):
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="world_memberships")
    role = models.CharField(max_length=10, choices=MEMBER_ROLES, default=Role.VIEWER)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["world", "user"], name="uniq_member_per_world")]
        indexes = [models.Index(fields=["user", "world"])]

    def __str__(self):
        return f"{self.user_id}@{self.world_id}:{self.role}"


class WorldInvite(models.Model):
    """An invitation: personal (``email`` set, single use) or a shareable link (``email`` empty)."""

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="invites")
    token = models.CharField(max_length=64, unique=True, default=new_token, editable=False)
    email = models.EmailField(blank=True, default="")
    role = models.CharField(max_length=10, choices=MEMBER_ROLES, default=Role.VIEWER)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    uses = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["email"])]

    @property
    def is_link(self):
        return not self.email

    def problem(self):
        """Why the invite cannot be used (None when it is valid)."""
        if self.revoked_at:
            return "Запрошення відкликано."
        if self.declined_at:
            return "Запрошення відхилено."
        if self.expires_at and self.expires_at <= timezone.now():
            return "Термін дії запрошення минув."
        limit = 1 if self.email else self.max_uses
        if limit is not None and self.uses >= limit:
            return "Запрошення вже використано."
        return None


class Comment(models.Model):
    """A remark on a chapter or an encyclopedia page. Comments never change the text itself."""

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="comments")
    chapter = models.ForeignKey("books.Chapter", on_delete=models.CASCADE, null=True, blank=True, related_name="comments")
    page = models.ForeignKey("pages.Page", on_delete=models.CASCADE, null=True, blank=True, related_name="comments")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    body = models.TextField(max_length=4000)
    quote = models.CharField(max_length=500, blank=True, help_text="Фрагмент тексту, до якого стосується коментар.")
    # Which occurrence of ``quote`` in the text was selected (0 = the first), so the highlight lands on that place.
    quote_occurrence = models.PositiveIntegerField(default=0)
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["chapter", "resolved"]), models.Index(fields=["page", "resolved"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(chapter__isnull=False, page__isnull=True) | models.Q(chapter__isnull=True, page__isnull=False),
                name="comment_has_one_target",
            ),
        ]
