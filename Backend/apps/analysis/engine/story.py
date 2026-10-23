"""Story memory for whole-book analysis.

A small local model cannot read a whole novel at once, so the book is read in order, piece by
piece. For each piece the model gets:

* a compact *world brief*: only the characters, factions, events and encyclopedia pages that
  are actually mentioned in it (statuses, dates, memberships, short descriptions);
* *story memory*: facts recorded from earlier chapters (and earlier pieces of the same chapter)
  about those same entities — "lost an arm", "the sword was broken", "learned the secret";

and returns both possible contradictions and the new facts of this piece. Facts are kept only
when their quote is really in the text, so the memory cannot fill up with invented events.
"""
from dataclasses import dataclass, field

from .mentions import MentionMatcher
from .retrieval import build_context

# Gemini reads a whole chapter at once, so it also gets a generous memory and world brief.
BRIEF_CHARS = 8000
MEMORY_CHARS = 9000
MEMORY_ITEMS = 60


@dataclass
class Fact:
    who: str
    fact: str
    quote: str
    chapter_id: int
    chapter_title: str
    order: int  # global reading order (book chapters in order); later facts are "more recent"
    start: int | None = None
    refs: list = field(default_factory=list)  # ["c:12", "p:5", "f:3"]
    kind: str = "other"  # death / injury / item / place / knowledge / relation / other

    def as_dict(self):
        return {
            "who": self.who, "fact": self.fact, "quote": self.quote, "chapter_id": self.chapter_id,
            "chapter_title": self.chapter_title, "order": self.order, "start": self.start, "refs": self.refs,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            who=str(d.get("who", ""))[:120], fact=str(d.get("fact", ""))[:300], quote=str(d.get("quote", ""))[:400],
            chapter_id=int(d.get("chapter_id") or 0), chapter_title=str(d.get("chapter_title", ""))[:200],
            order=int(d.get("order") or 0), start=d.get("start"), refs=[str(r) for r in d.get("refs", [])][:20],
            kind=str(d.get("kind") or "other")[:20],
        )


class EntityIndex:
    """Finds world entities (characters, factions, other pages) in text, with Ukrainian inflection.

    A character's or faction's own page shares its names, so it is indexed as that character /
    faction (one entity), never twice — otherwise every short name would look ambiguous.
    """

    def __init__(self, snapshot):
        self.snapshot = snapshot
        entities = [(f"c:{c.id}", c.names()) for c in snapshot.characters]
        entities += [(f"f:{f.id}", [f.name]) for f in snapshot.factions]
        self.page_of = {}
        for page in snapshot.lore:
            if page.source_type != "page":
                continue
            if page.character_id:
                self.page_of[f"c:{page.character_id}"] = page
            elif page.faction_id:
                self.page_of[f"f:{page.faction_id}"] = page
            else:
                entities.append((f"p:{page.id}", [page.title]))
        self.matcher = MentionMatcher(entities)

    def keys(self, text):
        seen = []
        for m in self.matcher.find(text or ""):
            if m.entity_id not in seen:
                seen.append(m.entity_id)
        return seen


def status_line(c, chapter):
    """The character's status as it holds *in this chapter*, or None when it cannot be placed in time.

    A "dead" status without a death chapter or comparable dates is left out: it may describe the end of
    the story or a sequel, and used against every chapter it turns a living character into a "plot hole".
    """
    if c.status in ("dead", "missing"):
        state = c.dead_in(chapter) if chapter is not None else None
        word = STATUS_UK[c.status]
        where = f"у розділі «{c.death_chapter[2]}»" if c.death_chapter else c.death.text()
        if state is True:
            return f"Статус у цьому розділі: {word} ({where})"
        if state is False:
            return f"Статус у цьому розділі: живий (за енциклопедією {'загине' if c.status == 'dead' else 'зникне'} пізніше — {where})"
        return None
    if c.status and c.status != "unknown":
        return f"Статус: {STATUS_UK.get(c.status, c.status)}"
    return None


def world_brief(snapshot, index, text, keys, chapter=None):
    """Short facts about the entities mentioned in ``text``: {"characters": [...], "events", "lore"}.

    ``chapter`` (ChapterS) places time-dependent facts — statuses and the date of death — in the story.
    """
    context = build_context(snapshot, text, budget_chars=BRIEF_CHARS // 2, max_entries=8)
    chars = {f"c:{c.id}": c for c in snapshot.characters}
    factions = {f.id: f.name for f in snapshot.factions}
    characters = []
    for key in keys:
        c = chars.get(key)
        if c is None:
            continue
        lines = [f"Імʼя: {c.name}"]
        if c.aliases:
            lines.append("Інші імена: " + ", ".join(c.aliases[:5]))
        status = status_line(c, chapter)
        if status:
            lines.append(status)
        if c.birth.known:
            lines.append(f"Народження: {c.birth.text()}")
        if c.death.known and chapter is not None and chapter.story_time.known:
            lines.append(f"Смерть: {c.death.text()} (час дії розділу: {chapter.story_time.text()})")
        member_of = [factions[m.faction_id] for m in snapshot.memberships if m.character_id == c.id and m.faction_id in factions]
        if member_of:
            lines.append("Фракції: " + ", ".join(member_of[:4]))
        if c.profile:
            lines.append(c.profile[:700])
        characters.append((c, "\n".join(lines)))
        if len(characters) >= 15:
            break
    mentioned = {int(k[2:]) for k in keys if k.startswith("c:")}
    events = [e for e in snapshot.events if any(cid in mentioned for cid, _ in e.participants)][:15]
    lore, used = [], sum(len(t) for _, t in characters)
    for item in context["lore"]:
        if item["entry"].character_id:  # the character's own page is already in the brief
            continue
        snippet = item["snippet"][:900]
        if used + len(snippet) > BRIEF_CHARS:
            break
        lore.append((item["entry"], snippet))
        used += len(snippet)
    return {"characters": characters, "events": events, "lore": lore}


STATUS_UK = {"alive": "живий", "dead": "загинув", "missing": "зник безвісти", "other": "інше"}


def recall(facts, keys, before_order, current_chapter_id=None):
    """Earlier facts about the mentioned entities, most recent first, within the memory budget.

    ``before_order`` excludes facts from later chapters (a rescan of chapter 5 must not "know"
    chapter 40). Facts of the current chapter are included (earlier pieces of it).
    """
    wanted = set(keys)
    picked, used = [], 0
    candidates = [f for f in facts if (f.order < before_order or f.chapter_id == current_chapter_id) and wanted & set(f.refs)]
    candidates.sort(key=lambda f: (-f.order, -(f.start or 0)))
    for f in candidates:
        size = len(f.fact) + len(f.quote) + 40
        if used + size > MEMORY_CHARS:
            continue
        picked.append(f)
        used += size
        if len(picked) >= MEMORY_ITEMS:
            break
    return sorted(picked, key=lambda f: (f.order, f.start or 0))
