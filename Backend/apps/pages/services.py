"""Page domain logic: entity sync, link extraction, property validation, tree operations."""
import copy
import math

from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import ValidationError

from apps.books.documents import document_stats, page_link_ids, text_to_document
from apps.worlds.models import Character, Faction, LoreEntry

from .models import Page, PageLink, PageProperty
from .templates import BUILTIN_TEMPLATES, LORE_CATEGORY_BY_TYPE, PAGE_TYPE_BY_LORE_CATEGORY

MAX_PROPERTIES = 60
MAX_TAGS = 50


# --- properties ---------------------------------------------------------------------------

def clean_property_value(kind, value, world):
    """Validate a property value for its kind. Page references must point to the same world."""
    if value is None or value == "" or value == []:
        return None
    if kind == PageProperty.Kind.TEXT:
        if not isinstance(value, str) or len(value) > 5000:
            raise ValidationError({"value": "Очікується текст до 5000 символів."})
        return value
    if kind == PageProperty.Kind.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValidationError({"value": "Очікується число."})
        return value
    if kind == PageProperty.Kind.CHECKBOX:
        if not isinstance(value, bool):
            raise ValidationError({"value": "Очікується так/ні."})
        return value
    if kind == PageProperty.Kind.DATE:
        # In-world date: a display label plus an optional comparable number (same scheme as the timeline).
        if not isinstance(value, dict):
            raise ValidationError({"value": "Очікується {label, key}."})
        label = value.get("label", "")
        key = value.get("key")
        if not isinstance(label, str) or len(label) > 120:
            raise ValidationError({"value": "Некоректна мітка дати."})
        if key is not None and (isinstance(key, bool) or not isinstance(key, (int, float)) or not math.isfinite(key)):
            raise ValidationError({"value": "Ключ дати має бути числом."})
        return {"label": label, "key": key}
    if kind == PageProperty.Kind.TAGS:
        if not isinstance(value, list) or len(value) > MAX_TAGS or not all(isinstance(v, str) and 0 < len(v.strip()) <= 60 for v in value):
            raise ValidationError({"value": "Очікується список коротких значень."})
        return list(dict.fromkeys(v.strip() for v in value))
    if kind in (PageProperty.Kind.PAGE, PageProperty.Kind.PAGES):
        ids = value if kind == PageProperty.Kind.PAGES else [value]
        if not isinstance(ids, list) or len(ids) > 100 or not all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in ids):
            raise ValidationError({"value": "Очікується id сторінки."})
        found = set(Page.objects.filter(world=world, pk__in=ids).values_list("id", flat=True))
        if found != set(ids):
            raise ValidationError({"value": "Посилання можуть вести лише на сторінки цього світу."})
        return ids if kind == PageProperty.Kind.PAGES else ids[0]
    raise ValidationError({"kind": "Невідомий тип властивості."})


def property_page_ids(prop):
    if prop.kind == PageProperty.Kind.PAGE and isinstance(prop.value, int):
        return [prop.value]
    if prop.kind == PageProperty.Kind.PAGES and isinstance(prop.value, list):
        return [v for v in prop.value if isinstance(v, int)]
    return []


# --- links -----------------------------------------------------------------------------------

def rebuild_links(page, origin):
    """Recompute links of one origin. Targets outside the page's world are stored as broken (target=None)."""
    if origin == PageLink.Origin.CONTENT:
        ids = page_link_ids(page.content)
    else:
        ids = list(dict.fromkeys(i for p in page.properties.all() for i in property_page_ids(p)))
    valid = set(Page.objects.filter(world_id=page.world_id, pk__in=ids).values_list("id", flat=True))
    PageLink.objects.filter(source=page, origin=origin).delete()
    PageLink.objects.bulk_create(
        PageLink(source=page, target_id=ref if ref in valid else None, target_ref=ref, origin=origin) for ref in ids
    )


# --- linked structured records -------------------------------------------------------------

def sync_entity(page):
    """Push title/aliases/text from the page to its linked record (one direction: page → record)."""
    if page.character_id:
        Character.objects.filter(pk=page.character_id).update(name=page.title[:200], aliases=page.aliases, aliases_text="\n".join(page.aliases))
    elif page.faction_id:
        Faction.objects.filter(pk=page.faction_id).update(name=page.title[:200])
    elif page.lore_entry_id:
        LoreEntry.objects.filter(pk=page.lore_entry_id).update(title=page.title[:200], content=page.plain_text)


def create_entity(page, entity, lore_category=None):
    if entity == "character":
        page.character = Character.objects.create(world=page.world, name=page.title[:200], aliases=page.aliases)
    elif entity == "faction":
        page.faction = Faction.objects.create(world=page.world, name=page.title[:200])
    elif entity == "lore":
        category = lore_category or LORE_CATEGORY_BY_TYPE.get(page.page_type, "custom")
        page.lore_entry = LoreEntry.objects.create(
            world=page.world, title=page.title[:200], content=page.plain_text, category=category,
            custom_category=page.page_type[:60] if category == "custom" else "",
        )


def next_sort_order(world, parent):
    last = Page.objects.filter(world=world, parent=parent).aggregate(m=Max("sort_order"))["m"]
    return 0 if last is None else last + 1


@transaction.atomic
def create_page(world, title, parent=None, template=None, user_template=None, page_type=None, icon=None):
    """Create a page, optionally from a built-in (`template` key) or user template."""
    spec = BUILTIN_TEMPLATES["blank"]
    if user_template is not None:
        spec = {
            "page_type": user_template.page_type, "icon": user_template.icon, "entity": None,
            "content": user_template.content, "properties": user_template.properties,
        }
    elif template:
        if template not in BUILTIN_TEMPLATES:
            raise ValidationError({"template": "Невідомий шаблон."})
        spec = BUILTIN_TEMPLATES[template]
    content = copy.deepcopy(spec["content"])
    text, _ = document_stats(content)
    page = Page(
        world=world, parent=parent, title=title.strip()[:200] or "Без назви",
        page_type=(page_type or spec["page_type"])[:40], icon=icon if icon is not None else spec["icon"],
        content=content, plain_text=text, sort_order=next_sort_order(world, parent),
    )
    if spec.get("entity"):
        create_entity(page, spec["entity"], spec.get("lore_category"))
    page.save()
    PageProperty.objects.bulk_create(
        PageProperty(page=page, label=p["label"][:80], kind=p["kind"], order=i) for i, p in enumerate(spec["properties"])
    )
    return page


def page_for_record(record, kind):
    """Return the page of a structured record, creating one if needed (records created via graph/API)."""
    try:
        existing = record.page
    except Page.DoesNotExist:
        existing = None
    if existing is not None:
        return existing
    if kind == "character":
        page_type, field, title, text = "character", "character", record.name, ""
    elif kind == "faction":
        page_type, field, title, text = "faction", "faction", record.name, record.description
    else:
        page_type, field, title, text = PAGE_TYPE_BY_LORE_CATEGORY.get(record.category, "lore"), "lore_entry", record.title, record.content
    content = text_to_document(text)
    plain, _ = document_stats(content)
    page = Page(world=record.world, title=title[:200], page_type=page_type, content=content, plain_text=plain,
                sort_order=next_sort_order(record.world, None), aliases=list(getattr(record, "aliases", []) or []))
    setattr(page, field, record)
    page.save()
    return page


# --- tree ----------------------------------------------------------------------------------

def descendants(page):
    """All descendant ids (iterative BFS, single query per level)."""
    result, frontier = [], [page.id]
    while frontier:
        frontier = list(Page.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
        result.extend(frontier)
    return result


@transaction.atomic
def move_page(page, parent, position=None):
    if parent is not None:
        if parent.world_id != page.world_id:
            raise ValidationError({"parent": "Батьківська сторінка має бути з того самого світу."})
        if parent.id == page.id or parent.id in descendants(page):
            raise ValidationError({"parent": "Сторінку не можна вкласти саму в себе або в її підсторінку."})
    siblings = list(Page.objects.select_for_update().filter(world_id=page.world_id, parent=parent).exclude(pk=page.pk).order_by("sort_order", "id"))
    index = len(siblings) if position is None else max(0, min(position, len(siblings)))
    siblings.insert(index, page)
    page.parent = parent
    for order, item in enumerate(siblings):
        item.sort_order = order
    Page.objects.bulk_update(siblings, ["sort_order"])
    page.save(update_fields=["parent", "sort_order", "updated_at"])
    return page


@transaction.atomic
def delete_page(page, children_mode):
    """children_mode: None (refuse if there are children), "lift" or "delete"."""
    child_ids = descendants(page)
    if child_ids and children_mode not in ("lift", "delete"):
        raise ValidationError({"children": f"Сторінка має {len(child_ids)} вкладених сторінок. Оберіть: підняти їх або видалити разом."})
    if children_mode == "lift":
        for child in Page.objects.filter(parent=page).order_by("sort_order"):
            move_page(child, page.parent)
        child_ids = []
    pages = list(Page.objects.filter(pk__in=[page.id, *child_ids]))
    for p in pages:
        for field in ("character", "faction", "lore_entry"):
            record = getattr(p, field)
            if record is not None:
                record.delete()  # the page owns its linked record
        if p.cover:
            p.cover.delete(save=False)
        Page.objects.filter(pk=p.pk).delete()
    return len(pages)
