"""Built-in page templates.

A template is only a starting point: initial section headings in the text, an initial set of
properties (all optional, renamable, removable) and, for some types, a linked structured record
(character / faction / lore entry) used by graphs, the timeline and the analyser.
"""


def sections(*titles):
    content = []
    for title in titles:
        content.append({"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": title}]})
        content.append({"type": "paragraph"})
    return {"type": "doc", "content": content or [{"type": "paragraph"}]}


def prop(label, kind="text"):
    return {"label": label, "kind": kind}


BUILTIN_TEMPLATES = {
    "blank": {
        "name": "Порожня сторінка", "icon": "", "page_type": "note", "entity": None,
        "content": sections(), "properties": [],
    },
    "character": {
        "name": "Персонаж", "icon": "👤", "page_type": "character", "entity": "character",
        "content": sections("Біографія", "Зовнішність", "Характер", "Здібності", "Нотатки"),
        "properties": [prop("Короткий опис"), prop("Вік"), prop("Цілі"), prop("Страхи")],
    },
    "faction": {
        "name": "Фракція", "icon": "🛡️", "page_type": "faction", "entity": "faction",
        "content": sections("Опис", "Історія", "Структура", "Нотатки"),
        "properties": [prop("Цілі"), prop("Ідеологія"), prop("Лідер", "page"), prop("Штаб", "page")],
    },
    "location": {
        "name": "Локація", "icon": "📍", "page_type": "location", "entity": "lore", "lore_category": "location",
        "content": sections("Опис", "Історія", "Мешканці", "Нотатки"),
        "properties": [prop("Регіон", "page"), prop("Клімат"), prop("Населення", "number")],
    },
    "item": {
        "name": "Предмет", "icon": "💎", "page_type": "item", "entity": "lore", "lore_category": "item",
        "content": sections("Опис", "Походження", "Властивості"),
        "properties": [prop("Власник", "page"), prop("Рідкість")],
    },
    "creature": {
        "name": "Істота", "icon": "🐉", "page_type": "creature", "entity": "lore", "lore_category": "creature",
        "content": sections("Опис", "Поведінка", "Середовище"),
        "properties": [prop("Ареал", "pages"), prop("Небезпека")],
    },
    "event": {
        "name": "Подія", "icon": "📜", "page_type": "event", "entity": "lore", "lore_category": "history",
        "content": sections("Що сталося", "Причини", "Наслідки"),
        "properties": [prop("Дата", "date"), prop("Учасники", "pages"), prop("Місце", "page")],
    },
    "lore": {
        "name": "Запис лору", "icon": "📖", "page_type": "lore", "entity": "lore", "lore_category": "history",
        "content": sections(), "properties": [prop("Теги", "tags")],
    },
}

# page_type -> LoreEntry.category for lore-linked pages created outside of a template.
LORE_CATEGORY_BY_TYPE = {
    "location": "location", "item": "item", "creature": "creature", "event": "history", "lore": "history",
    "magic": "magic", "culture": "culture", "religion": "religion", "rules": "rules", "technology": "technology",
    "geography": "geography", "history": "history",
}
PAGE_TYPE_BY_LORE_CATEGORY = {
    "location": "location", "item": "item", "creature": "creature", "history": "lore", "geography": "location",
    "magic": "magic", "culture": "culture", "technology": "technology", "religion": "religion", "rules": "rules",
    "custom": "lore",
}
