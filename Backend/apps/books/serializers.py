from django.db import transaction
from rest_framework import serializers

from apps.worlds.models import World

from .documents import document_stats, validate_document
from .models import Book, Chapter, ChapterVersion


class OwnedWorldField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return World.objects.none()
        return World.objects.filter(owner=request.user)


class BookSerializer(serializers.ModelSerializer):
    world = OwnedWorldField(required=False)
    world_name = serializers.CharField(source="world.name", read_only=True)
    new_world_name = serializers.CharField(write_only=True, required=False, max_length=200)
    chapters_count = serializers.IntegerField(read_only=True, default=0)
    done_chapters = serializers.IntegerField(read_only=True, default=0)
    word_count = serializers.IntegerField(read_only=True, default=0)
    progress = serializers.SerializerMethodField()
    has_cover = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            "id", "world", "world_name", "new_world_name", "title", "description", "genre", "status",
            "manuscript_format", "accent", "has_cover", "chapters_count", "done_chapters", "word_count", "progress",
            "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_has_cover(self, obj) -> bool:
        return bool(obj.cover)

    def get_progress(self, obj) -> int:
        total = getattr(obj, "chapters_count", 0) or 0
        done = getattr(obj, "done_chapters", 0) or 0
        return round(100 * done / total) if total else 0

    def validate(self, attrs):
        if self.instance is None and not attrs.get("world") and not attrs.get("new_world_name"):
            raise serializers.ValidationError({"world": "Оберіть світ або вкажіть назву нового світу."})
        if self.instance is not None and "world" in attrs and attrs["world"] != self.instance.world:
            raise serializers.ValidationError({"world": "Книгу не можна перенести в інший світ."})
        return attrs

    @transaction.atomic
    def create(self, validated):
        new_world_name = validated.pop("new_world_name", None)
        if not validated.get("world"):
            validated["world"] = World.objects.create(
                owner=self.context["request"].user,
                name=new_world_name.strip(),
                genre=validated.get("genre", ""),
                description=validated.get("description", ""),
            )
        return super().create(validated)

    def update(self, instance, validated):
        validated.pop("new_world_name", None)
        return super().update(instance, validated)


class ChapterListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chapter
        fields = [
            "id", "book", "title", "order", "word_count", "status", "revision", "story_time_key",
            "story_time_label", "is_flashback", "narrator_unreliable", "created_at", "updated_at",
        ]
        read_only_fields = ["book", "order", "word_count", "revision", "created_at", "updated_at"]


class ChapterSerializer(ChapterListSerializer):
    content = serializers.JSONField(required=False)
    base_revision = serializers.IntegerField(write_only=True, required=False, min_value=1)
    snapshot = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta(ChapterListSerializer.Meta):
        fields = ChapterListSerializer.Meta.fields + ["content", "plain_text", "base_revision", "snapshot"]
        read_only_fields = ChapterListSerializer.Meta.read_only_fields + ["plain_text"]

    def validate_content(self, value):
        return validate_document(value)

    def validate(self, attrs):
        if "content" in attrs:
            text, words = document_stats(attrs["content"])
            attrs["plain_text"] = text
            attrs["word_count"] = words
        return attrs


class ChapterVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChapterVersion
        fields = ["id", "chapter", "revision", "title", "word_count", "reason", "created_at"]


class ChapterVersionDetailSerializer(ChapterVersionSerializer):
    class Meta(ChapterVersionSerializer.Meta):
        fields = ChapterVersionSerializer.Meta.fields + ["content", "plain_text"]


class ReorderSerializer(serializers.Serializer):
    order = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False, max_length=5000)


class DocxImportSerializer(serializers.Serializer):
    MODES = [("new_chapter", "new_chapter"), ("split_headings", "split_headings"), ("replace_chapter", "replace_chapter")]

    file = serializers.FileField()
    book = serializers.IntegerField(min_value=1)
    mode = serializers.ChoiceField(choices=MODES, default="new_chapter")
    chapter = serializers.IntegerField(min_value=1, required=False)
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
