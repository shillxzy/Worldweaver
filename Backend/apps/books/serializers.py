from django.db import transaction
from rest_framework import serializers

from apps.common.scoping import EDIT, accessible_worlds
from apps.common.users import display_name
from apps.worlds.models import World

from .documents import document_stats, validate_document
from .models import Arc, Book, Chapter, ChapterVersion


class OwnedWorldField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return World.objects.none()
        return accessible_worlds(request.user, EDIT)


class BookSerializer(serializers.ModelSerializer):
    world = OwnedWorldField(required=False)
    world_name = serializers.CharField(source="world.name", read_only=True)
    new_world_name = serializers.CharField(write_only=True, required=False, max_length=200)
    chapters_count = serializers.IntegerField(read_only=True, default=0)
    done_chapters = serializers.IntegerField(read_only=True, default=0)
    word_count = serializers.IntegerField(read_only=True, default=0)
    progress = serializers.SerializerMethodField()
    has_cover = serializers.SerializerMethodField()
    my_role = serializers.CharField(read_only=True, default="owner")
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            "id", "world", "world_name", "new_world_name", "title", "description", "genre", "status",
            "manuscript_format", "accent", "has_cover", "chapters_count", "done_chapters", "word_count", "progress",
            "my_role", "owner_name", "is_public", "created_at", "updated_at",
        ]
        read_only_fields = ["is_public", "created_at", "updated_at"]

    def get_owner_name(self, obj) -> str:
        return display_name(obj.world.owner)

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


class ArcSerializer(serializers.ModelSerializer):
    # A range of chapters (in reading order) to put into the arc; omitted = chapters stay as they are.
    first_chapter = serializers.IntegerField(write_only=True, required=False, min_value=1)
    last_chapter = serializers.IntegerField(write_only=True, required=False, min_value=1)

    class Meta:
        model = Arc
        fields = ["id", "book", "title", "first_chapter", "last_chapter", "created_at"]
        read_only_fields = ["book", "created_at"]

    def validate(self, attrs):
        if ("first_chapter" in attrs) != ("last_chapter" in attrs):
            raise serializers.ValidationError("Вкажіть і перший, і останній розділ арки.")
        return attrs


class ChapterListSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Chapter
        fields = [
            "id", "book", "arc", "title", "order", "word_count", "status", "revision", "story_time_key",
            "story_time_label", "is_flashback", "narrator_unreliable", "is_public", "updated_by_name",
            "created_at", "updated_at",
        ]
        read_only_fields = ["book", "order", "word_count", "revision", "is_public", "created_at", "updated_at"]

    def get_updated_by_name(self, obj) -> str:
        return display_name(obj.updated_by)

    def get_fields(self):
        fields = super().get_fields()
        view = self.context.get("view")
        # Only arcs of this chapter's book can be chosen: others look like they do not exist.
        has_book = view is not None and hasattr(view, "get_book") and "book_pk" in getattr(view, "kwargs", {})  # not in schema generation
        fields["arc"].queryset = Arc.objects.filter(book=view.get_book()) if has_book else Arc.objects.none()
        return fields


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
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = ChapterVersion
        fields = ["id", "chapter", "revision", "title", "word_count", "reason", "author_name", "created_at"]

    def get_author_name(self, obj) -> str:
        return display_name(obj.author)


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
    split_level = serializers.IntegerField(min_value=1, max_value=3, required=False)


class DocxPreviewSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    split_level = serializers.IntegerField(min_value=1, max_value=3, required=False)
