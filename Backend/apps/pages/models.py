"""Encyclopedia pages: free-form documents with optional typed properties, a tree structure and links.

A page may be linked to a structured world record (Character, Faction, LoreEntry) so that graphs,
the timeline and the consistency analyser keep working on structured data while the author edits
one free-form page.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.books.models import empty_document
from apps.worlds.models import Character, Faction, LoreEntry, World


class Page(models.Model):
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="pages")
    # CASCADE at the database level so deleting a world/account works; the API itself refuses to
    # delete a page with children unless the author explicitly chooses "lift" or "delete" (services.delete_page).
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    sort_order = models.IntegerField(default=0)
    title = models.CharField(max_length=200)
    icon = models.CharField(max_length=16, blank=True)
    cover = models.ImageField(upload_to="page_covers/", null=True, blank=True)
    page_type = models.CharField(max_length=40, default="note", help_text="Вільний тип: note, character, location, … або власний.")
    aliases = models.JSONField(default=list, blank=True)
    # Plain-text copy of aliases for portable case-insensitive search (kept in sync in save()).
    aliases_text = models.TextField(blank=True, default="", editable=False)
    content = models.JSONField(default=empty_document)
    plain_text = models.TextField(blank=True, default="")
    revision = models.PositiveIntegerField(default=1)
    is_public = models.BooleanField(default=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    character = models.OneToOneField(Character, null=True, blank=True, on_delete=models.SET_NULL, related_name="page")
    faction = models.OneToOneField(Faction, null=True, blank=True, on_delete=models.SET_NULL, related_name="page")
    lore_entry = models.OneToOneField(LoreEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="page")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "title", "id"]
        indexes = [
            models.Index(fields=["world", "parent", "sort_order"]),
            models.Index(fields=["world", "page_type"]),
            models.Index(fields=["world", "-updated_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(character__isnull=True, faction__isnull=True)
                    | Q(character__isnull=True, lore_entry__isnull=True)
                    | Q(faction__isnull=True, lore_entry__isnull=True)
                ),
                name="page_single_entity",
            )
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.aliases_text = "\n".join(a for a in (self.aliases or []) if isinstance(a, str))
        if kwargs.get("update_fields") is not None and "aliases" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "aliases_text"}
        super().save(*args, **kwargs)

    @property
    def entity(self):
        if self.character_id:
            return "character", self.character_id
        if self.faction_id:
            return "faction", self.faction_id
        if self.lore_entry_id:
            return "lore", self.lore_entry_id
        return None, None


class PageProperty(models.Model):
    class Kind(models.TextChoices):
        TEXT = "text", "Текст"
        NUMBER = "number", "Число"
        DATE = "date", "Дата у світі"
        CHECKBOX = "checkbox", "Прапорець"
        TAGS = "tags", "Список значень"
        PAGE = "page", "Посилання на сторінку"
        PAGES = "pages", "Посилання на сторінки"

    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="properties")
    label = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEXT)
    value = models.JSONField(null=True, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class PageLink(models.Model):
    """A reference from one page to another, extracted from text links and page-type properties."""

    class Origin(models.TextChoices):
        CONTENT = "content", "Текст"
        PROPERTY = "property", "Властивість"

    source = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="outgoing_links")
    target = models.ForeignKey(Page, null=True, blank=True, on_delete=models.SET_NULL, related_name="incoming_links")
    target_ref = models.PositiveBigIntegerField(help_text="Id, на який посилалися (лишається, якщо сторінку видалено).")
    origin = models.CharField(max_length=8, choices=Origin.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "target_ref", "origin"], name="uniq_page_link")]
        indexes = [models.Index(fields=["target"])]


class PageTemplate(models.Model):
    """A user-defined starting configuration for new pages (built-in ones live in templates.py)."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="page_templates")
    world = models.ForeignKey(World, null=True, blank=True, on_delete=models.CASCADE, related_name="page_templates")
    name = models.CharField(max_length=80)
    icon = models.CharField(max_length=16, blank=True)
    page_type = models.CharField(max_length=40, default="note")
    content = models.JSONField(default=empty_document)
    properties = models.JSONField(default=list, blank=True, help_text='[{"label": ..., "kind": ...}]')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
