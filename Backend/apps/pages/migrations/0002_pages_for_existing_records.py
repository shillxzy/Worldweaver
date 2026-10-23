"""Create an encyclopedia page for every existing character, faction and lore entry.

Non-destructive: the original records stay untouched; their free text is copied into the page
(as sections) and short fields become editable page properties. Reversible (removes only the
pages created here, identified by their linked record).
"""
from django.db import migrations

PAGE_TYPE_BY_CATEGORY = {
    "location": "location", "item": "item", "creature": "creature", "history": "lore", "geography": "location",
    "magic": "magic", "culture": "culture", "technology": "technology", "religion": "religion", "rules": "rules",
    "custom": "lore",
}
ICONS = {"character": "👤", "faction": "🛡️", "location": "📍", "item": "💎", "creature": "🐉", "lore": "📖"}


def paragraphs(text):
    out = []
    for block in (text or "").replace("\r\n", "\n").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        inline = []
        for i, line in enumerate(block.split("\n")):
            if i:
                inline.append({"type": "hardBreak"})
            if line:
                inline.append({"type": "text", "text": line})
        out.append({"type": "paragraph", "content": inline})
    return out


def heading(text):
    return {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": text}]}


def build_doc(sections):
    """sections: [(heading or None, text)] — empty texts are skipped."""
    content, plain = [], []
    for title, text in sections:
        body = paragraphs(text)
        if not body:
            continue
        if title:
            content.append(heading(title))
            plain.append(title)
        content.extend(body)
        plain.append(text.strip())
    return {"type": "doc", "content": content or [{"type": "paragraph"}]}, "\n\n".join(plain)


def forwards(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    PageProperty = apps.get_model("pages", "PageProperty")
    Character = apps.get_model("worlds", "Character")
    Faction = apps.get_model("worlds", "Faction")
    LoreEntry = apps.get_model("worlds", "LoreEntry")
    order = {}

    def next_order(world_id):
        order[world_id] = order.get(world_id, Page.objects.filter(world_id=world_id, parent__isnull=True).count()) + 1
        return order[world_id]

    def add_props(page, props):
        PageProperty.objects.bulk_create(
            PageProperty(page=page, label=label[:80], kind=kind, value=value, order=i)
            for i, (label, kind, value) in enumerate(props) if value not in (None, "", [])
        )

    for c in Character.objects.filter(page__isnull=True):
        doc, text = build_doc([
            ("Біографія", c.biography), ("Зовнішність", c.appearance), ("Характер", c.personality),
            ("Цілі", c.goals), ("Здібності", c.abilities), ("Нотатки", c.notes),
        ])
        aliases = [a for a in (c.aliases or []) if isinstance(a, str)]
        page = Page.objects.create(
            world_id=c.world_id, title=c.name, icon=ICONS["character"], page_type="character", content=doc, plain_text=text,
            aliases=aliases, aliases_text="\n".join(aliases), character_id=c.id, sort_order=next_order(c.world_id),
        )
        props = [("Короткий опис", "text", c.summary), ("Вік", "text", c.age_text)]
        props += [(f.get("label", "Факт"), "text", f.get("value", "")) for f in (c.facts or []) if isinstance(f, dict)]
        add_props(page, props)

    for f in Faction.objects.filter(page__isnull=True):
        doc, text = build_doc([(None, f.description)])
        page = Page.objects.create(
            world_id=f.world_id, title=f.name, icon=f.emblem or ICONS["faction"], page_type="faction", content=doc,
            plain_text=text, faction_id=f.id, sort_order=next_order(f.world_id),
        )
        add_props(page, [("Цілі", "text", f.goals), ("Ідеологія", "text", f.ideology)])

    for e in LoreEntry.objects.filter(page__isnull=True):
        page_type = PAGE_TYPE_BY_CATEGORY.get(e.category, "lore")
        if e.category == "custom" and e.custom_category:
            page_type = e.custom_category.strip().lower()[:40] or "lore"
        doc, text = build_doc([(None, e.content)])
        page = Page.objects.create(
            world_id=e.world_id, title=e.title, icon=ICONS.get(page_type, ICONS["lore"]), page_type=page_type,
            content=doc, plain_text=text, lore_entry_id=e.id, sort_order=next_order(e.world_id),
        )
        add_props(page, [("Теги", "tags", [t.name for t in e.tags.all()])])


def backwards(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    Page.objects.filter(parent__isnull=True).exclude(character__isnull=True, faction__isnull=True, lore_entry__isnull=True).filter(children__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0001_initial"),
        ("worlds", "0003_graphlayout"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
