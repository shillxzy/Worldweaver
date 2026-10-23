from rest_framework import serializers

from apps.books.documents import document_stats, validate_document

from .models import Page, PageProperty, PageTemplate
from .services import clean_property_value


class PageListSerializer(serializers.ModelSerializer):
    has_children = serializers.BooleanField(read_only=True, default=False)
    has_cover = serializers.SerializerMethodField()
    entity_type = serializers.SerializerMethodField()
    entity_id = serializers.SerializerMethodField()

    class Meta:
        model = Page
        fields = [
            "id", "title", "icon", "page_type", "parent", "sort_order", "aliases", "has_children", "has_cover",
            "entity_type", "entity_id", "updated_at",
        ]

    def get_has_cover(self, obj) -> bool:
        return bool(obj.cover)

    def get_entity_type(self, obj) -> str | None:
        return obj.entity[0]

    def get_entity_id(self, obj) -> int | None:
        return obj.entity[1]


class PropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = PageProperty
        fields = ["id", "label", "kind", "value", "order"]
        read_only_fields = ["order"]

    def validate_label(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Назва властивості не може бути порожньою.")
        return value

    def validate(self, attrs):
        kind = attrs.get("kind", getattr(self.instance, "kind", PageProperty.Kind.TEXT))
        if "value" in attrs or "kind" in attrs:
            value = attrs.get("value", getattr(self.instance, "value", None))
            if self.instance is not None and "kind" in attrs and attrs["kind"] != self.instance.kind and "value" not in attrs:
                value = None  # changing the type resets the value
            attrs["value"] = clean_property_value(kind, value, self.context["world"])
        return attrs


class StringListField(serializers.ListField):
    child = serializers.CharField(max_length=120, trim_whitespace=True)


class PageSerializer(PageListSerializer):
    content = serializers.JSONField(required=False)
    aliases = StringListField(required=False, max_length=30)
    properties = PropertySerializer(many=True, read_only=True)
    base_revision = serializers.IntegerField(write_only=True, required=False, min_value=1)

    class Meta(PageListSerializer.Meta):
        fields = PageListSerializer.Meta.fields + ["content", "plain_text", "revision", "properties", "base_revision", "created_at"]
        read_only_fields = ["parent", "sort_order", "plain_text", "revision", "created_at"]

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Назва не може бути порожньою.")
        return value

    def validate_page_type(self, value):
        value = value.strip().lower()[:40]
        return value or "note"

    def validate_aliases(self, value):
        return list(dict.fromkeys(a for a in value if a))

    def validate_content(self, value):
        return validate_document(value)

    def validate(self, attrs):
        if "content" in attrs:
            attrs["plain_text"], _ = document_stats(attrs["content"])
        return attrs


class PageCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    parent = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    template = serializers.CharField(max_length=40, required=False, allow_blank=True)
    user_template = serializers.IntegerField(min_value=1, required=False)
    page_type = serializers.CharField(max_length=40, required=False)
    icon = serializers.CharField(max_length=16, required=False, allow_blank=True)


class MoveSerializer(serializers.Serializer):
    parent = serializers.IntegerField(min_value=1, allow_null=True)
    position = serializers.IntegerField(min_value=0, required=False)


class TemplateSerializer(serializers.ModelSerializer):
    key = serializers.SerializerMethodField()
    builtin = serializers.SerializerMethodField()

    class Meta:
        model = PageTemplate
        fields = ["id", "key", "builtin", "name", "icon", "page_type", "properties", "world", "created_at"]
        read_only_fields = fields

    def get_key(self, obj) -> str:
        return f"user:{obj.id}"

    def get_builtin(self, obj) -> bool:
        return False
