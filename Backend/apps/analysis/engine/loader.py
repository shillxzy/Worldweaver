"""Build a WorldSnapshot from the database (one query per entity type)."""
from decimal import Decimal

from apps.books.models import Chapter
from apps.worlds.models import (
    Character,
    EventParticipant,
    Faction,
    FactionMembership,
    LoreEntry,
    Relationship,
    TimelineDependency,
    TimelineEvent,
)

from .types import (
    APPROXIMATE,
    EXACT,
    UNKNOWN,
    ChapterS,
    CharacterS,
    DependencyS,
    EventS,
    FactionS,
    LoreS,
    MembershipS,
    RelationshipS,
    TimePoint,
    WorldSnapshot,
)


def point(key, precision=EXACT, uncertainty=None, label=""):
    if key is None:
        return TimePoint(None, UNKNOWN, Decimal("0"), label)
    return TimePoint(Decimal(key), precision or EXACT, Decimal(uncertainty or 0), label)


def load_snapshot(world, chapter_qs=None):
    snap = WorldSnapshot(id=world.id, name=world.name)
    for c in Character.objects.filter(world=world):
        snap.characters.append(CharacterS(
            id=c.id, name=c.name, aliases=list(c.aliases or []), status=c.status,
            birth=point(c.birth_key, c.birth_precision if c.birth_precision != UNKNOWN else APPROXIMATE, label=c.birth_label),
            death=point(c.death_key, c.death_precision if c.death_precision != UNKNOWN else APPROXIMATE, label=c.death_label),
            world_id=c.world_id,
        ))
    snap.factions = [FactionS(f.id, f.name, f.world_id) for f in Faction.objects.filter(world=world)]
    participants = {}
    for p in EventParticipant.objects.filter(event__world=world).select_related("character"):
        participants.setdefault(p.event_id, []).append((p.character_id, p.role))
        if p.character.world_id != world.id and snap.character(p.character_id) is None:
            # keep foreign characters visible so the cross-world rule can report them
            snap.characters.append(CharacterS(id=p.character_id, name=p.character.name, world_id=p.character.world_id))
    chapter_links = {}
    for link in TimelineEvent.chapters.through.objects.filter(timelineevent__world=world):
        chapter_links.setdefault(link.timelineevent_id, []).append(link.chapter_id)
    for e in TimelineEvent.objects.filter(world=world):
        snap.events.append(EventS(
            id=e.id, title=e.title,
            start=point(e.start_key, e.precision, e.uncertainty, e.start_label),
            end=point(e.end_key, e.precision, e.uncertainty, e.end_label),
            participants=participants.get(e.id, []), chapter_ids=chapter_links.get(e.id, []), world_id=e.world_id,
        ))
    snap.dependencies = [
        DependencyS(d.id, d.before_id, d.after_id, d.kind, d.min_gap)
        for d in TimelineDependency.objects.filter(world=world)
    ]
    snap.memberships = [
        MembershipS(m.id, m.character_id, m.faction_id, point(m.start_key, label=m.start_label), point(m.end_key, label=m.end_label))
        for m in FactionMembership.objects.filter(character__world=world)
    ]
    sides = [f"{s}_{t}" for s in ("source", "target") for t in Relationship.ENTITY_TYPES]
    for r in Relationship.objects.filter(world=world).select_related(*sides):
        s_type, s_obj = r.source
        t_type, t_obj = r.target
        snap.relationships.append(RelationshipS(
            id=r.id, kind=r.kind, source=(s_type, s_obj.id), target=(t_type, t_obj.id),
            start=point(r.start_key, label=r.start_label), end=point(r.end_key, label=r.end_label),
            source_world=s_obj.world_id, target_world=t_obj.world_id, world_id=r.world_id,
        ))
    for entry in LoreEntry.objects.filter(world=world).prefetch_related("tags"):
        snap.lore.append(LoreS(entry.id, entry.title, entry.content, entry.category, [t.name for t in entry.tags.all()]))
    chapters = chapter_qs if chapter_qs is not None else Chapter.objects.filter(book__world=world)
    for ch in chapters.only("id", "title", "order", "plain_text", "book_id", "story_time_key", "story_time_label", "is_flashback", "narrator_unreliable"):
        snap.chapters.append(ChapterS(
            id=ch.id, title=ch.title, order=ch.order, text=ch.plain_text, book_id=ch.book_id,
            story_time=point(ch.story_time_key, label=ch.story_time_label),
            is_flashback=ch.is_flashback, narrator_unreliable=ch.narrator_unreliable,
        ))
    return snap
