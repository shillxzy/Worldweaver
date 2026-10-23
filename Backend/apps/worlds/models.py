"""World-building entities: worlds, lore, characters, factions, relationships, timeline.

Time inside a fictional world is NOT a Python datetime. Every time point is stored as:

* ``*_key``   – a decimal number comparable within one world (e.g. year 212.5);
* ``*_label`` – what the author wants to see ("212 рік Епохи Глибин", "весна 340");
* ``precision`` – exact / approximate / unknown, plus ``uncertainty`` (± in key units).

Unknown or missing keys are never treated as errors by the analysis engine.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

TIME_DIGITS = dict(max_digits=20, decimal_places=4)

hex_color = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Колір має бути у форматі #RRGGBB.")


class Precision(models.TextChoices):
    EXACT = "exact", "Точна"
    APPROXIMATE = "approximate", "Приблизна"
    UNKNOWN = "unknown", "Невідома"


class World(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="worlds")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    genre = models.CharField(max_length=120, blank=True)
    rules = models.TextField(blank=True, help_text="Загальні правила світу.")
    tech_level = models.CharField(max_length=120, blank=True)
    magic_system = models.TextField(blank=True, help_text="Магія або інші системи світу.")
    time_unit_label = models.CharField(max_length=40, blank=True, default="рік")
    calendar_notes = models.TextField(blank=True)
    # Public read-only site: off by default; only items explicitly marked public are shown.
    public_enabled = models.BooleanField(default=False)
    public_token = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.name


class Tag(models.Model):
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=60)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["world", "name"], name="uniq_tag_per_world")]

    def __str__(self):
        return self.name


class Character(models.Model):
    class Status(models.TextChoices):
        ALIVE = "alive", "Живий"
        DEAD = "dead", "Загинув"
        MISSING = "missing", "Зниклий"
        UNKNOWN = "unknown", "Невідомо"
        OTHER = "other", "Інше"

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="characters")
    name = models.CharField(max_length=200)
    aliases = models.JSONField(default=list, blank=True, help_text="Альтернативні імена (список рядків).")
    # Plain-text copy of aliases for portable case-insensitive search (kept in sync in save()).
    aliases_text = models.TextField(blank=True, default="", editable=False)
    summary = models.CharField(max_length=500, blank=True)
    biography = models.TextField(blank=True)
    personality = models.TextField(blank=True)
    appearance = models.TextField(blank=True)
    goals = models.TextField(blank=True)
    abilities = models.TextField(blank=True)
    age_text = models.CharField(max_length=60, blank=True, help_text="Вік у довільній формі, якщо відомий.")
    birth_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    birth_label = models.CharField(max_length=120, blank=True)
    birth_precision = models.CharField(max_length=12, choices=Precision.choices, default=Precision.UNKNOWN)
    death_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    death_label = models.CharField(max_length=120, blank=True)
    death_precision = models.CharField(max_length=12, choices=Precision.choices, default=Precision.UNKNOWN)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNKNOWN)
    # When a death / disappearance happens in the manuscript: without it a "dead" status has no time and
    # must not be used against chapters (it may describe the end of the story or a sequel).
    death_chapter = models.ForeignKey("books.Chapter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    portrait = models.ImageField(upload_to="portraits/", null=True, blank=True)
    # Card banner: an uploaded image wins over the colour; with neither, a colour is derived from the name.
    banner = models.ImageField(upload_to="banners/", null=True, blank=True)
    banner_color = models.CharField(max_length=7, blank=True, default="", validators=[hex_color])
    facts = models.JSONField(default=list, blank=True, help_text='Список {"label": ..., "value": ...}.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["world", "name"]), models.Index(fields=["world", "status"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.aliases_text = "\n".join(a for a in (self.aliases or []) if isinstance(a, str))
        if kwargs.get("update_fields") is not None and "aliases" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "aliases_text"}
        super().save(*args, **kwargs)

    def all_names(self):
        return [self.name, *[a for a in self.aliases if isinstance(a, str) and a.strip()]]


class Faction(models.Model):
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="factions")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    goals = models.TextField(blank=True)
    ideology = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#e879a8", validators=[hex_color])
    emblem = models.CharField(max_length=8, blank=True, help_text="Короткий символ (емодзі або літера).")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["world", "name"])]

    def __str__(self):
        return self.name


class FactionMembership(models.Model):
    """Historical membership of a character in a faction."""

    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name="memberships")
    faction = models.ForeignKey(Faction, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=120, blank=True)
    start_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    start_label = models.CharField(max_length=120, blank=True)
    end_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    end_label = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["start_key", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(start_key__isnull=True) | Q(end_key__isnull=True) | Q(end_key__gte=models.F("start_key")),
                name="membership_end_after_start",
            )
        ]

    def clean(self):
        if self.character_id and self.faction_id and self.character.world_id != self.faction.world_id:
            raise ValidationError("Персонаж і фракція належать різним світам.")


class LoreEntry(models.Model):
    class Category(models.TextChoices):
        HISTORY = "history", "Історія"
        GEOGRAPHY = "geography", "Географія"
        LOCATION = "location", "Локація"
        MAGIC = "magic", "Магія"
        CULTURE = "culture", "Культура"
        TECHNOLOGY = "technology", "Технології"
        RELIGION = "religion", "Релігія"
        RULES = "rules", "Правила"
        ITEM = "item", "Предмет"
        CREATURE = "creature", "Істота"
        CUSTOM = "custom", "Власна категорія"

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="lore_entries")
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.HISTORY)
    custom_category = models.CharField(max_length=60, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="lore_entries")
    related_characters = models.ManyToManyField(Character, blank=True, related_name="lore_entries")
    related_factions = models.ManyToManyField(Faction, blank=True, related_name="lore_entries")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        verbose_name_plural = "lore entries"
        indexes = [models.Index(fields=["world", "category"]), models.Index(fields=["world", "title"])]

    def __str__(self):
        return self.title


class TimelineEvent(models.Model):
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    start_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    start_label = models.CharField(max_length=120, blank=True)
    end_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    end_label = models.CharField(max_length=120, blank=True)
    precision = models.CharField(max_length=12, choices=Precision.choices, default=Precision.EXACT)
    uncertainty = models.DecimalField(default=0, **TIME_DIGITS, help_text="± у одиницях ключа часу.")
    sort_order = models.IntegerField(default=0, help_text="Порядок для подій без відомої дати.")
    factions = models.ManyToManyField(Faction, blank=True, related_name="events")
    lore_entries = models.ManyToManyField(LoreEntry, blank=True, related_name="events")
    chapters = models.ManyToManyField("books.Chapter", blank=True, related_name="events")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_key", "sort_order", "id"]
        indexes = [models.Index(fields=["world", "start_key"])]

    def __str__(self):
        return self.title


class EventParticipant(models.Model):
    class Role(models.TextChoices):
        PARTICIPANT = "participant", "Учасник"
        MENTIONED = "mentioned", "Згадується"
        POSTHUMOUS = "posthumous", "Посмертно / пояснено правилом світу"

    event = models.ForeignKey(TimelineEvent, on_delete=models.CASCADE, related_name="participants")
    character = models.ForeignKey(Character, on_delete=models.CASCADE, related_name="event_participations")
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.PARTICIPANT)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "character"], name="uniq_event_participant")]


class TimelineDependency(models.Model):
    """Directed temporal constraint: ``before`` must happen no later than ``after``."""

    class Kind(models.TextChoices):
        BEFORE = "before", "Відбувається раніше"
        CAUSES = "causes", "Спричиняє"

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="dependencies")
    before = models.ForeignKey(TimelineEvent, on_delete=models.CASCADE, related_name="dependents")
    after = models.ForeignKey(TimelineEvent, on_delete=models.CASCADE, related_name="prerequisites")
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.BEFORE)
    min_gap = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    description = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["before", "after"], name="uniq_dependency"),
            models.CheckConstraint(condition=~Q(before=models.F("after")), name="dependency_not_self"),
        ]


class Relationship(models.Model):
    """Typed relationship between two world entities.

    Each side references exactly one entity through a real foreign key, so integrity and
    cascading deletes are enforced by the database (no generic object deserialization).
    """

    class Kind(models.TextChoices):
        ALLIANCE = "alliance", "Союз"
        ENMITY = "enmity", "Ворожнеча"
        FAMILY = "family", "Родинний звʼязок"
        SUBORDINATION = "subordination", "Підпорядкування"
        MEMBERSHIP = "membership", "Членство"
        ACQUAINTANCE = "acquaintance", "Знайомство"
        MENTORSHIP = "mentorship", "Наставництво"
        OTHER = "other", "Інше"

    ENTITY_TYPES = ("character", "faction", "event", "lore")
    # Kinds that form hierarchies in which cycles are forbidden.
    ACYCLIC_KINDS = (Kind.SUBORDINATION, Kind.MENTORSHIP)

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="relationships")
    kind = models.CharField(max_length=14, choices=Kind.choices)
    source_character = models.ForeignKey(Character, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    source_faction = models.ForeignKey(Faction, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    source_event = models.ForeignKey(TimelineEvent, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    source_lore = models.ForeignKey(LoreEntry, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    target_character = models.ForeignKey(Character, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    target_faction = models.ForeignKey(Faction, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    target_event = models.ForeignKey(TimelineEvent, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    target_lore = models.ForeignKey(LoreEntry, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    description = models.TextField(blank=True)
    directed = models.BooleanField(default=True)
    start_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    start_label = models.CharField(max_length=120, blank=True)
    end_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    end_label = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(source_character__isnull=False, source_faction__isnull=True, source_event__isnull=True, source_lore__isnull=True)
                    | Q(source_character__isnull=True, source_faction__isnull=False, source_event__isnull=True, source_lore__isnull=True)
                    | Q(source_character__isnull=True, source_faction__isnull=True, source_event__isnull=False, source_lore__isnull=True)
                    | Q(source_character__isnull=True, source_faction__isnull=True, source_event__isnull=True, source_lore__isnull=False)
                ),
                name="relationship_one_source",
            ),
            models.CheckConstraint(
                condition=(
                    Q(target_character__isnull=False, target_faction__isnull=True, target_event__isnull=True, target_lore__isnull=True)
                    | Q(target_character__isnull=True, target_faction__isnull=False, target_event__isnull=True, target_lore__isnull=True)
                    | Q(target_character__isnull=True, target_faction__isnull=True, target_event__isnull=False, target_lore__isnull=True)
                    | Q(target_character__isnull=True, target_faction__isnull=True, target_event__isnull=True, target_lore__isnull=False)
                ),
                name="relationship_one_target",
            ),
            models.CheckConstraint(
                condition=Q(start_key__isnull=True) | Q(end_key__isnull=True) | Q(end_key__gte=models.F("start_key")),
                name="relationship_end_after_start",
            ),
        ]

    def _side(self, prefix):
        for entity_type in self.ENTITY_TYPES:
            obj = getattr(self, f"{prefix}_{entity_type}")
            if obj is not None:
                return entity_type, obj
        return None, None

    @property
    def source(self):
        return self._side("source")

    @property
    def target(self):
        return self._side("target")


class GraphLayout(models.Model):
    """Saved node positions of an auto-generated world graph (per view)."""

    class View(models.TextChoices):
        FACTIONS = "factions", "Фракції"
        RELATIONS = "relations", "Звʼязки та родичі"

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="graph_layouts")
    view = models.CharField(max_length=10, choices=View.choices)
    positions = models.JSONField(default=dict, blank=True, help_text='{"character:1": [x, y], ...}')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["world", "view"], name="uniq_graph_layout")]
