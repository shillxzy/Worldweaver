from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from rest_framework import serializers

from apps.analysis.engine.graph import Graph
from apps.books.models import Chapter
from apps.common.scoping import WorldRelatedField, parse_id

from .models import (
    Character,
    EventParticipant,
    Faction,
    FactionMembership,
    LoreEntry,
    Relationship,
    Tag,
    TimelineDependency,
    TimelineEvent,
    World,
)


def _check_range(attrs, instance, start="start_key", end="end_key"):
    start_value = attrs.get(start, getattr(instance, start, None) if instance else None)
    end_value = attrs.get(end, getattr(instance, end, None) if instance else None)
    if start_value is not None and end_value is not None and end_value < start_value:
        raise serializers.ValidationError({end: "Кінець не може бути раніше за початок."})


def _page_id(record):
    try:
        return record.page.id
    except ObjectDoesNotExist:  # the record has no page yet
        return None


class WorldSerializer(serializers.ModelSerializer):
    characters_count = serializers.IntegerField(read_only=True, default=0)
    factions_count = serializers.IntegerField(read_only=True, default=0)
    lore_count = serializers.IntegerField(read_only=True, default=0)
    events_count = serializers.IntegerField(read_only=True, default=0)
    books_count = serializers.IntegerField(read_only=True, default=0)
    my_role = serializers.CharField(read_only=True, default="owner")

    class Meta:
        model = World
        fields = [
            "id", "name", "description", "genre", "rules", "tech_level", "magic_system",
            "time_unit_label", "calendar_notes", "created_at", "updated_at",
            "characters_count", "factions_count", "lore_count", "events_count", "books_count", "my_role",
        ]
        read_only_fields = ["created_at", "updated_at"]


class StringListField(serializers.ListField):
    def __init__(self, max_items=30, max_length=120, **kwargs):
        kwargs.setdefault("child", serializers.CharField(max_length=max_length, allow_blank=False, trim_whitespace=True))
        kwargs.setdefault("max_length", max_items)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)


class TagListField(StringListField):
    def to_representation(self, value):
        return [tag.name for tag in value.all()] if hasattr(value, "all") else super().to_representation(value)


class FactSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=120)
    value = serializers.CharField(max_length=1000, allow_blank=True)


class MembershipBriefSerializer(serializers.ModelSerializer):
    faction_name = serializers.CharField(source="faction.name", read_only=True)
    faction_color = serializers.CharField(source="faction.color", read_only=True)

    class Meta:
        model = FactionMembership
        fields = ["id", "faction", "faction_name", "faction_color", "role", "start_label", "end_label", "start_key", "end_key"]


class CharacterSerializer(serializers.ModelSerializer):
    aliases = StringListField(max_items=20)
    facts = FactSerializer(many=True, required=False)
    memberships = MembershipBriefSerializer(many=True, read_only=True)
    has_portrait = serializers.SerializerMethodField()
    has_banner = serializers.SerializerMethodField()
    page_id = serializers.SerializerMethodField()

    class Meta:
        model = Character
        fields = [
            "id", "name", "aliases", "summary", "biography", "personality", "appearance", "goals",
            "abilities", "age_text", "birth_key", "birth_label", "birth_precision", "death_key",
            "death_label", "death_precision", "status", "facts", "notes", "has_portrait",
            "has_banner", "banner_color", "page_id", "memberships", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_has_portrait(self, obj) -> bool:
        return bool(obj.portrait)

    def get_has_banner(self, obj) -> bool:
        return bool(obj.banner)

    def get_page_id(self, obj) -> int | None:
        return _page_id(obj)

    def validate_aliases(self, value):
        seen, result = set(), []
        for alias in value:
            if alias.lower() not in seen:
                seen.add(alias.lower())
                result.append(alias)
        return result

    def validate_facts(self, value):
        if len(value) > 50:
            raise serializers.ValidationError("Не більше 50 фактів.")
        return value

    def validate(self, attrs):
        _check_range(attrs, self.instance, "birth_key", "death_key")
        return attrs


class FactionSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(read_only=True, default=0)
    page_id = serializers.SerializerMethodField()

    def get_page_id(self, obj) -> int | None:
        return _page_id(obj)

    class Meta:
        model = Faction
        fields = ["id", "name", "description", "goals", "ideology", "color", "emblem", "members_count", "page_id", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class MembershipSerializer(serializers.ModelSerializer):
    character = WorldRelatedField(Character)
    faction = WorldRelatedField(Faction)
    character_name = serializers.CharField(source="character.name", read_only=True)
    faction_name = serializers.CharField(source="faction.name", read_only=True)

    class Meta:
        model = FactionMembership
        fields = [
            "id", "character", "character_name", "faction", "faction_name", "role",
            "start_key", "start_label", "end_key", "end_label", "notes",
        ]

    def validate(self, attrs):
        _check_range(attrs, self.instance)
        return attrs


class LoreEntrySerializer(serializers.ModelSerializer):
    tags = TagListField(max_items=30, max_length=60)
    related_characters = WorldRelatedField(Character, many=True, required=False)
    related_factions = WorldRelatedField(Faction, many=True, required=False)

    class Meta:
        model = LoreEntry
        fields = [
            "id", "title", "content", "category", "custom_category", "tags",
            "related_characters", "related_factions", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        category = attrs.get("category", getattr(self.instance, "category", None))
        if category == LoreEntry.Category.CUSTOM and not attrs.get("custom_category", getattr(self.instance, "custom_category", "")):
            raise serializers.ValidationError({"custom_category": "Вкажіть назву власної категорії."})
        return attrs

    def _set_tags(self, entry, names):
        world = self.context["world"]
        tags = []
        for name in names:
            tag, _ = Tag.objects.get_or_create(world=world, name=name.strip().lower()[:60])
            tags.append(tag)
        entry.tags.set(tags)

    @transaction.atomic
    def create(self, validated):
        tags = validated.pop("tags", [])
        entry = super().create(validated)
        self._set_tags(entry, tags)
        return entry

    @transaction.atomic
    def update(self, instance, validated):
        tags = validated.pop("tags", None)
        entry = super().update(instance, validated)
        if tags is not None:
            self._set_tags(entry, tags)
        return entry


class ParticipantSerializer(serializers.Serializer):
    character = WorldRelatedField(Character)
    role = serializers.ChoiceField(choices=EventParticipant.Role.choices, default=EventParticipant.Role.PARTICIPANT)
    note = serializers.CharField(max_length=300, allow_blank=True, required=False, default="")

    def to_representation(self, instance):
        return {
            "character": instance.character_id,
            "character_name": instance.character.name,
            "role": instance.role,
            "note": instance.note,
        }


class TimelineEventSerializer(serializers.ModelSerializer):
    participants = ParticipantSerializer(many=True, required=False)
    factions = WorldRelatedField(Faction, many=True, required=False)
    lore_entries = WorldRelatedField(LoreEntry, many=True, required=False)
    chapters = WorldRelatedField(Chapter, world_path="book__world", many=True, required=False)

    class Meta:
        model = TimelineEvent
        fields = [
            "id", "title", "description", "start_key", "start_label", "end_key", "end_label",
            "precision", "uncertainty", "sort_order", "participants", "factions", "lore_entries",
            "chapters", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_uncertainty(self, value):
        if value < 0:
            raise serializers.ValidationError("Невизначеність не може бути відʼємною.")
        return value

    def validate_participants(self, value):
        ids = [p["character"].id for p in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Персонаж указаний кілька разів.")
        return value

    def validate(self, attrs):
        _check_range(attrs, self.instance)
        return attrs

    def _set_participants(self, event, participants):
        event.participants.all().delete()
        EventParticipant.objects.bulk_create(
            EventParticipant(event=event, character=p["character"], role=p["role"], note=p.get("note", ""))
            for p in participants
        )

    @transaction.atomic
    def create(self, validated):
        participants = validated.pop("participants", [])
        event = super().create(validated)
        self._set_participants(event, participants)
        return event

    @transaction.atomic
    def update(self, instance, validated):
        participants = validated.pop("participants", None)
        event = super().update(instance, validated)
        if participants is not None:
            self._set_participants(event, participants)
        return event


def dependency_graph(world, exclude_id=None):
    graph = Graph()
    qs = TimelineDependency.objects.filter(world=world)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    for dep in qs.only("before_id", "after_id"):
        graph.add_edge(dep.before_id, dep.after_id)
    return graph


class DependencySerializer(serializers.ModelSerializer):
    before = WorldRelatedField(TimelineEvent)
    after = WorldRelatedField(TimelineEvent)
    before_title = serializers.CharField(source="before.title", read_only=True)
    after_title = serializers.CharField(source="after.title", read_only=True)

    class Meta:
        model = TimelineDependency
        fields = ["id", "before", "before_title", "after", "after_title", "kind", "min_gap", "description", "created_at"]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        before = attrs.get("before", getattr(self.instance, "before", None))
        after = attrs.get("after", getattr(self.instance, "after", None))
        if before == after:
            raise serializers.ValidationError("Подія не може залежати сама від себе.")
        if attrs.get("min_gap") is not None and attrs["min_gap"] < 0:
            raise serializers.ValidationError({"min_gap": "Мінімальний проміжок не може бути відʼємним."})
        graph = dependency_graph(self.context["world"], exclude_id=getattr(self.instance, "pk", None))
        if graph.would_create_cycle(before.id, after.id):
            raise serializers.ValidationError("Ця залежність створює цикл у хронології.")
        return attrs


ENTITY_MODELS = {"character": Character, "faction": Faction, "event": TimelineEvent, "lore": LoreEntry}


class EntityRefSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=[(t, t) for t in Relationship.ENTITY_TYPES])
    id = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        model = ENTITY_MODELS[attrs["type"]]
        world = self.context.get("world")
        if parse_id(attrs["id"]) is None:
            raise serializers.ValidationError({"id": "Некоректний ідентифікатор."})
        obj = model.objects.filter(world=world, pk=attrs["id"]).first()
        if obj is None:
            raise serializers.ValidationError({"id": "Сутність не існує в цьому світі."})
        attrs["object"] = obj
        return attrs


def entity_label(entity_type, obj):
    return getattr(obj, "name", None) or getattr(obj, "title", "")


class RelationshipSerializer(serializers.ModelSerializer):
    source = EntityRefSerializer(write_only=True)
    target = EntityRefSerializer(write_only=True)

    class Meta:
        model = Relationship
        fields = [
            "id", "kind", "source", "target", "description", "directed",
            "start_key", "start_label", "end_key", "end_label", "created_at",
        ]
        read_only_fields = ["created_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for side in ("source", "target"):
            entity_type, obj = getattr(instance, side)
            data[side] = {"type": entity_type, "id": obj.id, "label": entity_label(entity_type, obj)} if obj else None
        return data

    def validate(self, attrs):
        _check_range(attrs, self.instance)
        source = attrs.get("source")
        target = attrs.get("target")
        if self.instance is None and (source is None or target is None):
            raise serializers.ValidationError("Потрібні source і target.")
        src_ref = (source["type"], source["object"].id) if source else self.instance.source[0:1] + (self.instance.source[1].id,)
        tgt_ref = (target["type"], target["object"].id) if target else self.instance.target[0:1] + (self.instance.target[1].id,)
        if src_ref == tgt_ref:
            raise serializers.ValidationError("Сутність не може мати звʼязок сама з собою.")
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        if kind in Relationship.ACYCLIC_KINDS:
            graph = Graph()
            existing = Relationship.objects.filter(world=self.context["world"], kind=kind)
            if self.instance is not None:
                existing = existing.exclude(pk=self.instance.pk)
            for rel in existing.select_related(*[f"{s}_{t}" for s in ("source", "target") for t in Relationship.ENTITY_TYPES]):
                s_type, s_obj = rel.source
                t_type, t_obj = rel.target
                graph.add_edge((s_type, s_obj.id), (t_type, t_obj.id))
            if graph.would_create_cycle(src_ref, tgt_ref):
                raise serializers.ValidationError(
                    {"kind": f"Звʼязок типу «{Relationship.Kind(kind).label}» утворив би цикл (наприклад, A підпорядковується B, а B — A)."}
                )
        return attrs

    @staticmethod
    def _apply_side(validated, side):
        ref = validated.pop(side, None)
        if ref is None:
            return
        for entity_type in Relationship.ENTITY_TYPES:
            validated[f"{side}_{entity_type}"] = ref["object"] if entity_type == ref["type"] else None

    def create(self, validated):
        self._apply_side(validated, "source")
        self._apply_side(validated, "target")
        return super().create(validated)

    def update(self, instance, validated):
        self._apply_side(validated, "source")
        self._apply_side(validated, "target")
        return super().update(instance, validated)
