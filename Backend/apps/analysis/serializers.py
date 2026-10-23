from rest_framework import serializers

from apps.books.models import Book, Chapter
from apps.common.scoping import EDIT, accessible_worlds
from apps.worlds.models import World

from .models import AnalysisJob, Evidence, Finding


class EvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evidence
        fields = ["id", "source_type", "source_id", "source_label", "quote", "position_start", "position_end", "verified"]


class FindingSerializer(serializers.ModelSerializer):
    evidence = EvidenceSerializer(many=True, read_only=True)
    chapter_title = serializers.CharField(source="chapter.title", read_only=True, default=None)
    book = serializers.IntegerField(source="chapter.book_id", read_only=True, default=None)

    class Meta:
        model = Finding
        fields = [
            "id", "job", "world", "chapter", "chapter_title", "book", "rule", "category", "severity", "source",
            "confidence", "summary", "explanation", "manuscript_quote", "position_start", "position_end",
            "quote_verified", "decision", "decision_note", "evidence", "created_at",
        ]
        read_only_fields = [f for f in fields if f not in ("decision", "decision_note")]


class AnalysisJobSerializer(serializers.ModelSerializer):
    world = serializers.PrimaryKeyRelatedField(queryset=World.objects.none(), required=False)
    book = serializers.PrimaryKeyRelatedField(queryset=Book.objects.none(), required=False, allow_null=True)
    chapter = serializers.PrimaryKeyRelatedField(queryset=Chapter.objects.none(), required=False, allow_null=True)
    text = serializers.CharField(write_only=True, required=False, allow_blank=False, max_length=50_000)
    findings_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = AnalysisJob
        fields = [
            "id", "world", "book", "chapter", "kind", "status", "use_ai", "params", "text", "progress",
            "progress_message", "cancel_requested", "error_code", "error_message", "model_name", "attempts",
            "created_at", "started_at", "finished_at", "stats", "findings_count",
        ]
        read_only_fields = [
            "status", "params", "progress", "progress_message", "cancel_requested", "error_code", "error_message",
            "model_name", "attempts", "created_at", "started_at", "finished_at", "stats",
        ]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # Running checks (and the AI) is part of working on the text: editors and above.
            worlds = accessible_worlds(request.user, EDIT)
            fields["world"].queryset = worlds
            fields["book"].queryset = Book.objects.filter(world__in=worlds)
            fields["chapter"].queryset = Chapter.objects.filter(book__world__in=worlds)
        return fields

    def validate(self, attrs):
        kind = attrs.get("kind")
        book, chapter = attrs.get("book"), attrs.get("chapter")
        if kind == AnalysisJob.Kind.CONSISTENCY:
            raise serializers.ValidationError({"kind": "Детерміновані перевірки запускаються через /worlds/{id}/consistency/."})
        if kind in (AnalysisJob.Kind.FRAGMENT, AnalysisJob.Kind.CHAPTER):
            if chapter is None:
                raise serializers.ValidationError({"chapter": "Вкажіть розділ."})
            book = chapter.book
        if kind == AnalysisJob.Kind.FRAGMENT and not attrs.get("text", "").strip():
            raise serializers.ValidationError({"text": "Вкажіть фрагмент тексту."})
        if kind in (AnalysisJob.Kind.BOOK, AnalysisJob.Kind.BOOK_WITH_LORE) and book is None:
            raise serializers.ValidationError({"book": "Вкажіть книгу."})
        if chapter is not None and book is not None and chapter.book_id != book.id:
            raise serializers.ValidationError({"chapter": "Розділ не належить цій книзі."})
        world = attrs.get("world") or book.world
        if world.id != book.world_id:
            raise serializers.ValidationError({"world": "Книга належить іншому світу."})
        attrs["world"], attrs["book"] = world, book
        text = attrs.pop("text", None)
        attrs["params"] = {"text": text} if text else {}
        return attrs
