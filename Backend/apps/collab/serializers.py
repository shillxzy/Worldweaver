from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from apps.common.users import display_name

from .models import LINK_ROLES, MEMBER_ROLES, Comment, Role, WorldInvite


def person(user, show_email=False):
    """Public face of a user inside a shared project."""
    if user is None:
        return None
    profile = getattr(user, "profile", None)
    data = {"id": user.pk, "name": display_name(user), "has_avatar": bool(profile and profile.avatar)}
    if show_email:
        data["email"] = user.email
    return data


class RoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=MEMBER_ROLES)


class TransferSerializer(serializers.Serializer):
    user = serializers.IntegerField(min_value=1)


class InviteCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=MEMBER_ROLES, default=Role.VIEWER)
    expires_in_days = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)
    max_uses = serializers.IntegerField(min_value=1, max_value=1000, required=False, allow_null=True)

    def validate(self, attrs):
        attrs["email"] = (attrs.get("email") or "").strip().lower()
        if not attrs["email"]:
            if attrs["role"] not in LINK_ROLES:
                raise serializers.ValidationError({"role": "Посилання може давати роль читача, коментатора або редактора."})
        elif attrs.get("max_uses"):
            raise serializers.ValidationError({"max_uses": "Особисте запрошення одноразове."})
        days = attrs.pop("expires_in_days", None)
        attrs["expires_at"] = timezone.now() + timedelta(days=days) if days else None
        return attrs


class InviteSerializer(serializers.ModelSerializer):
    kind = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = WorldInvite
        fields = ["id", "kind", "email", "role", "token", "created_by_name", "created_at", "expires_at", "max_uses", "uses", "status"]

    def get_kind(self, obj) -> str:
        return "link" if obj.is_link else "email"

    def get_status(self, obj) -> str:
        return obj.problem() or "active"

    def get_created_by_name(self, obj) -> str:
        return display_name(obj.created_by)


class CommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    resolved_by_name = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_resolve = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            "id", "chapter", "page", "parent", "author", "body", "quote", "quote_occurrence", "resolved", "resolved_by_name",
            "can_edit", "can_resolve", "can_delete", "created_at", "updated_at",
        ]
        read_only_fields = ["chapter", "page", "parent", "quote_occurrence", "resolved", "created_at", "updated_at"]

    def get_author(self, obj):
        return person(obj.author)

    def get_resolved_by_name(self, obj) -> str:
        return display_name(obj.resolved_by) if obj.resolved else ""

    def _mine(self, obj):
        return obj.author_id is not None and obj.author_id == self.context["request"].user.pk

    def get_can_edit(self, obj) -> bool:
        return self._mine(obj)

    def get_can_resolve(self, obj) -> bool:
        return obj.parent_id is None and (self._mine(obj) or self.context["can_edit_content"])

    def get_can_delete(self, obj) -> bool:
        return self._mine(obj) or self.context["can_manage"]


class CommentCreateSerializer(serializers.Serializer):
    chapter = serializers.IntegerField(min_value=1, required=False)
    page = serializers.IntegerField(min_value=1, required=False)
    parent = serializers.IntegerField(min_value=1, required=False)
    body = serializers.CharField(max_length=4000)
    quote = serializers.CharField(max_length=500, required=False, allow_blank=True)
    quote_occurrence = serializers.IntegerField(min_value=0, max_value=100000, required=False, default=0)

    def validate_body(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Коментар порожній.")
        return value


class CommentUpdateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000, required=False)
    resolved = serializers.BooleanField(required=False)


class PublicSettingsSerializer(serializers.Serializer):
    """Owner's switches for the public site; flags map ids to true/false."""

    enabled = serializers.BooleanField(required=False)
    regenerate = serializers.BooleanField(required=False, default=False)
    books = serializers.DictField(child=serializers.BooleanField(), required=False)
    chapters = serializers.DictField(child=serializers.BooleanField(), required=False)
    pages = serializers.DictField(child=serializers.BooleanField(), required=False)
