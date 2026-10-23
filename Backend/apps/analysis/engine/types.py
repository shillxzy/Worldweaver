"""Plain data structures used by the consistency engine.

The engine works on an in-memory snapshot of a world (``WorldSnapshot``) so that it can be
unit-tested and evaluated on a labelled dataset without a database.
"""
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

EXACT, APPROXIMATE, UNKNOWN = "exact", "approximate", "unknown"
# Tolerance (in world time units) applied to approximate points that have no explicit ±.
DEFAULT_APPROX_TOLERANCE = Decimal("1")

CONFIRMED, POTENTIAL, INSUFFICIENT, UNVERIFIED = "confirmed", "potential", "insufficient_data", "unverified"
INFO, WARNING, ERROR = "info", "warning", "error"


def fmt_number(value):
    """Decimal('340.0000') -> '340', Decimal('12.5000') -> '12.5' (never scientific notation)."""
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return text
    return str(value)


@dataclass(frozen=True)
class TimePoint:
    key: Optional[Decimal]
    precision: str = EXACT
    uncertainty: Decimal = Decimal("0")
    label: str = ""

    @property
    def known(self):
        return self.key is not None and self.precision != UNKNOWN

    @property
    def tolerance(self):
        if not self.known:
            return None
        if self.precision == APPROXIMATE:
            return max(self.uncertainty, DEFAULT_APPROX_TOLERANCE)
        return self.uncertainty

    @property
    def earliest(self):
        return self.key - self.tolerance if self.known else None

    @property
    def latest(self):
        return self.key + self.tolerance if self.known else None

    @property
    def is_exact(self):
        return self.known and self.precision == EXACT and self.uncertainty == 0

    def text(self):
        if self.label:
            return self.label
        if self.key is None:
            return "невідомо"
        prefix = "≈" if self.precision == APPROXIMATE else ""
        return f"{prefix}{fmt_number(self.key)}"


def compare_points(a: TimePoint, b: TimePoint):
    """Decide whether ``a`` is strictly later than ``b``.

    Returns one of:
      * "violation"  – certainly later, both points exact;
      * "likely"     – later even after allowing for uncertainty (some point approximate);
      * "borderline" – later by nominal value only, within the uncertainty margin;
      * None         – not later, or at least one point unknown.
    """
    if not (a.known and b.known):
        return None
    if a.key <= b.key:
        return None
    if a.is_exact and b.is_exact:
        return "violation"
    if a.earliest > b.latest:
        return "likely"
    return "borderline"


OUTCOME_CATEGORY = {"violation": (CONFIRMED, ERROR), "likely": (POTENTIAL, WARNING), "borderline": (INSUFFICIENT, INFO)}


@dataclass
class CharacterS:
    id: int
    name: str
    aliases: list = field(default_factory=list)
    status: str = "unknown"
    birth: TimePoint = TimePoint(None, UNKNOWN)
    death: TimePoint = TimePoint(None, UNKNOWN)
    world_id: Optional[int] = None
    profile: str = ""  # free text from the character's encyclopedia page (AI context)
    # (book_id, chapter order, chapter title) of the chapter where the death/disappearance happens, if set.
    death_chapter: Optional[tuple] = None

    def dead_in(self, chapter):
        """Is the character already dead (or missing) in ``chapter``? True / False / None (= unknown time).

        Anchored by the death chapter (same book: later chapters only) or by story time vs death time.
        An unanchored "dead" status is never applied to a chapter.
        """
        if self.status not in ("dead", "missing"):
            return False
        if self.death_chapter:
            book_id, order, _ = self.death_chapter
            if chapter.book_id == book_id:
                return chapter.order > order
        if self.death.known and chapter.story_time.known:
            return chapter.story_time.key > self.death.key
        return None

    def names(self):
        return [self.name, *[a for a in self.aliases if a]]


@dataclass
class EventS:
    id: int
    title: str
    start: TimePoint
    end: TimePoint = TimePoint(None, UNKNOWN)
    participants: list = field(default_factory=list)  # [(character_id, role)]
    chapter_ids: list = field(default_factory=list)
    world_id: Optional[int] = None

    @property
    def span_end(self):
        return self.end if self.end.known else self.start


@dataclass
class DependencyS:
    id: int
    before: int
    after: int
    kind: str = "before"
    min_gap: Optional[Decimal] = None


@dataclass
class MembershipS:
    id: int
    character_id: int
    faction_id: int
    start: TimePoint = TimePoint(None, UNKNOWN)
    end: TimePoint = TimePoint(None, UNKNOWN)


@dataclass
class FactionS:
    id: int
    name: str
    world_id: Optional[int] = None


@dataclass
class RelationshipS:
    id: int
    kind: str
    source: tuple  # (type, id)
    target: tuple
    start: TimePoint = TimePoint(None, UNKNOWN)
    end: TimePoint = TimePoint(None, UNKNOWN)
    source_world: Optional[int] = None
    target_world: Optional[int] = None
    world_id: Optional[int] = None


@dataclass
class LoreS:
    id: int
    title: str
    content: str = ""
    category: str = ""
    tags: list = field(default_factory=list)
    source_type: str = "lore"  # "page" for encyclopedia pages
    character_id: Optional[int] = None  # the page of a character / faction (same names: one entity)
    faction_id: Optional[int] = None


@dataclass
class ChapterS:
    id: int
    title: str
    order: int
    text: str
    book_id: Optional[int] = None
    story_time: TimePoint = TimePoint(None, UNKNOWN)
    is_flashback: bool = False
    narrator_unreliable: bool = False


@dataclass
class WorldSnapshot:
    id: Optional[int] = None
    name: str = ""
    characters: list = field(default_factory=list)
    factions: list = field(default_factory=list)
    events: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)
    memberships: list = field(default_factory=list)
    relationships: list = field(default_factory=list)
    lore: list = field(default_factory=list)
    chapters: list = field(default_factory=list)

    def character(self, cid):
        return self._index("characters").get(cid)

    def event(self, eid):
        return self._index("events").get(eid)

    def faction(self, fid):
        return self._index("factions").get(fid)

    def _index(self, attr):
        cache_name = f"_idx_{attr}"
        cache = self.__dict__.get(cache_name)
        if cache is None or len(cache) != len(getattr(self, attr)):
            cache = {obj.id: obj for obj in getattr(self, attr)}
            self.__dict__[cache_name] = cache
        return cache


@dataclass
class EvidenceDraft:
    source_type: str
    source_id: int
    label: str = ""
    quote: str = ""
    start: Optional[int] = None
    end: Optional[int] = None
    verified: bool = False


@dataclass
class FindingDraft:
    rule: str
    category: str
    severity: str
    summary: str
    explanation: str = ""
    source: str = "rules"
    confidence: Optional[float] = None
    chapter_id: Optional[int] = None
    quote: str = ""
    start: Optional[int] = None
    end: Optional[int] = None
    quote_verified: bool = False
    evidence: list = field(default_factory=list)
    subject: tuple = ()  # main entities, e.g. (("character", 3), ("event", 7)) — used for evaluation & dedupe

    def fingerprint(self):
        refs = sorted(f"{t}:{i}" for t, i in self.subject) or sorted(f"{e.source_type}:{e.source_id}" for e in self.evidence)
        raw = "|".join([self.rule, str(self.chapter_id or ""), *refs, (self.quote or "")[:80].lower()])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
