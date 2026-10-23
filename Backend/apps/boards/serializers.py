import json

from django.db import transaction
from rest_framework import serializers

from apps.books.models import Book
from apps.common.scoping import EDIT, accessible_worlds

from .models import Board, BoardConnection, BoardItem

DEFAULT_COLUMNS = [
    ("Сюжетні повороти", "#e879a8"),
    ("Ідеї для розділів", "#3fb8c9"),
    ("Чернетки", "#e0b36a"),
]


class BoardItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BoardItem
        fields = ["id", "board", "parent", "kind", "text", "color", "x", "y", "width", "height", "order", "metadata", "created_at", "updated_at"]
        read_only_fields = ["board", "created_at", "updated_at"]

    def get_fields(self):
        fields = super().get_fields()
        board = self.context.get("board")
        fields["parent"].queryset = BoardItem.objects.filter(board=board) if board else BoardItem.objects.none()
        return fields

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata має бути обʼєктом.")
        if len(json.dumps(value, ensure_ascii=False)) > 4000:
            raise serializers.ValidationError("metadata завелике.")
        return value

    def validate(self, attrs):
        for key in ("width", "height"):
            if key in attrs and not (10 <= attrs[key] <= 5000):
                raise serializers.ValidationError({key: "Розмір поза допустимими межами."})
        for key in ("x", "y"):
            if key in attrs and abs(attrs[key]) > 1_000_000:
                raise serializers.ValidationError({key: "Позиція поза допустимими межами."})
        parent = attrs.get("parent")
        if parent is not None and self.instance is not None and parent.pk == self.instance.pk:
            raise serializers.ValidationError({"parent": "Елемент не може бути власним батьком."})
        return attrs


class BoardConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BoardConnection
        fields = ["id", "board", "source", "target", "label", "created_at"]
        read_only_fields = ["board", "created_at"]

    def get_fields(self):
        fields = super().get_fields()
        board = self.context.get("board")
        qs = BoardItem.objects.filter(board=board) if board else BoardItem.objects.none()
        fields["source"].queryset = qs
        fields["target"].queryset = qs
        return fields

    def validate(self, attrs):
        if attrs.get("source") == attrs.get("target"):
            raise serializers.ValidationError("Елемент не можна зʼєднати сам із собою.")
        return attrs


class OwnedBookField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return Book.objects.filter(world__in=accessible_worlds(self.context["request"].user, EDIT))


class OwnedWorldField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return accessible_worlds(self.context["request"].user, EDIT)


class BoardSerializer(serializers.ModelSerializer):
    book = OwnedBookField(required=False, allow_null=True)
    world = OwnedWorldField(required=False, allow_null=True)
    with_default_columns = serializers.BooleanField(write_only=True, required=False, default=False)
    items = BoardItemSerializer(many=True, read_only=True)
    connections = BoardConnectionSerializer(many=True, read_only=True)

    class Meta:
        model = Board
        fields = ["id", "title", "book", "world", "with_default_columns", "items", "connections", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        if self.instance is None:
            if bool(attrs.get("book")) == bool(attrs.get("world")):
                raise serializers.ValidationError("Дошка має належати або книзі, або світу.")
        elif "book" in attrs or "world" in attrs:
            raise serializers.ValidationError("Власника дошки змінити не можна.")
        return attrs

    @transaction.atomic
    def create(self, validated):
        with_columns = validated.pop("with_default_columns", False)
        board = super().create(validated)
        if with_columns:
            BoardItem.objects.bulk_create(
                BoardItem(board=board, kind=BoardItem.Kind.COLUMN, text=title, color=color, x=i * 260, order=i)
                for i, (title, color) in enumerate(DEFAULT_COLUMNS)
            )
        return board

    def update(self, instance, validated):
        validated.pop("with_default_columns", None)
        return super().update(instance, validated)


class LayoutItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(min_value=1)
    x = serializers.FloatField(required=False)
    y = serializers.FloatField(required=False)
    order = serializers.IntegerField(required=False)
    parent = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class LayoutSerializer(serializers.Serializer):
    items = LayoutItemSerializer(many=True, max_length=2000)
