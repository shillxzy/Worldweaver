"""Deterministic heuristics over the manuscript text.

These rules connect the manuscript with world facts:

* ``dead_character_active``   – a character acts in a chapter set after their death;
* ``death_then_alive``        – a chapter states a character died, a later chapter shows them
                                acting, with no flashback / memory / resurrection marker;
* ``age_mismatch``            – an age stated in the text contradicts birth date + chapter time;
* ``age_inconsistent``        – ages stated in two chapters contradict the chapters' time gap;
* ``possible_name_typo``      – a capitalised word one letter (two in long names) away from a known name.

Every quote is taken verbatim from the chapter text and verified with ``find_quote``;
results are "potential" unless the facts are exact and formal.
"""
import re
from decimal import Decimal

from apps.common.text import find_quote

from .mentions import MentionMatcher, sentence_at, sentences, stem
from .types import (
    CONFIRMED,
    ERROR,
    INFO,
    INSUFFICIENT,
    OUTCOME_CATEGORY,
    POTENTIAL,
    WARNING,
    EvidenceDraft,
    FindingDraft,
    compare_points,
    fmt_number,
)

ACTION_RE = re.compile(
    r"(?i:\b(?:сказа[вл]|сказала|відпові(?:в|ла)|промови(?:в|ла)|прошепоті(?:в|ла)|крикну(?:в|ла)|"
    r"спита(?:в|ла)|запита(?:в|ла)|усміхну(?:вся|лася|лась)|посміхну(?:вся|лася|лась)|кивну(?:в|ла)|"
    r"зайш(?:ов|ла)|увійш(?:ов|ла)|вийш(?:ов|ла)|прийш(?:ов|ла)|підві(?:вся|лася|лась)|сі(?:в|ла)|"
    r"взя(?:в|ла)|подиви(?:вся|лася|лась)|глянув|глянула|зітхну(?:в|ла)|засмія(?:вся|лася|лась)|"
    r"стоя(?:в|ла)|сиді(?:в|ла)|ішов|ішла|йшов|йшла|біг|бігла|обійня(?:в|ла)|"
    r"махну(?:в|ла)|наказа(?:в|ла)|пообіця(?:в|ла)|поверну(?:вся|лася|лась)|чека(?:в|ла))\b)"
)
DIALOGUE_RE = re.compile(r"^\s*[—–-]\s")
MEMORY_RE = re.compile(
    r"(?i:згад\w*|спогад\w*|пам['’ʼ]?ят\w*|колись|давно|минул\w*|сн(?:и|о)\w*|снил\w*|наснил\w*|"
    r"привид\w*|дух\w*|могил\w*|похорон\w*|покійн\w*|мертв\w*|загибл\w*|портрет\w*|видінн\w*|марев\w*|"
    r"уяви\w*|ніби|наче|мов би)"
)
REVIVAL_RE = re.compile(r"(?i:воскрес\w*|ожи(?:в|ла|ли)\b|повернув(?:ся)? з мертвих|повернула(?:ся)? з мертвих|"
                        r"вижи(?:в|ла)|врятува\w*|не загину\w*|не поме\w*|інсценува\w*|підробив\w* смерть)")
DEATH_AFTER_NAME = r"(?:\s+(?:був|була)\s+(?:вбит\w*|убит\w*|страчен\w*))|(?:\s+(?:загину(?:в|ла)|поме(?:р|рла)|заги(?:нув|бла)|сконав|сконала|розбився|розбилася|потону(?:в|ла)))"
# "тіло" alone is not death ("влила отруту в тіло Андерсона" is about a living body): only a dead body counts.
DEATH_BEFORE_NAME = r"(?i:смерть|загибель|похорон\w*|мертве\s+тіло|труп|вбили|убили|стратили|вбивство)\s+"
# An attempt, a wound or a lethal threat is not a death unless the sentence also states the death itself.
ATTEMPT_RE = re.compile(r"(?i:спроб\w*|намага\w*|хоті\w*\s+вбити|хоче\s+вбити|отру\w*|смертельн\w*|доз[уиаою]\b|поранен\w*|"
                        r"майже|ледь|мало не)")
DEFINITE_DEATH_RE = re.compile(r"(?i:\bпоме(?:р|рла|рли)\b|\bзагину(?:в|ла|ли)\b|\bвбит\w*|\bубит\w*|\bмертв\w*|\bсконав\w*|\bтруп\w*)")
AGE_AFTER_NAME = re.compile(r"^\s*(?:було|виповнилося|виповнилось|минуло)\s+(\d{1,4})\s+(?:рік|роки|років)")
AGE_BEFORE_NAME = re.compile(r"(\d{1,4})[-‑]?річн(?:ий|а|ого|ої|ому|ій|ім|ою)\s+$")


def _verified_quote(text, sentence):
    span = find_quote(text, sentence)
    return (span[0], span[1], True) if span else (None, None, False)


class ManuscriptAnalyzer:
    def __init__(self, snapshot):
        self.snap = snapshot
        self.matcher = MentionMatcher([(c.id, c.names()) for c in snapshot.characters])
        self.chapters = sorted(snapshot.chapters, key=lambda ch: (ch.book_id or 0, ch.order, ch.id))
        self._mentions = {}
        self._sentences = {}

    def mentions(self, chapter):
        if chapter.id not in self._mentions:
            self._mentions[chapter.id] = self.matcher.find(chapter.text)
        return self._mentions[chapter.id]

    def spans(self, chapter):
        if chapter.id not in self._sentences:
            self._sentences[chapter.id] = list(sentences(chapter.text))
        return self._sentences[chapter.id]

    # --- helpers -----------------------------------------------------------------
    def _is_active(self, chapter, mention):
        """Does the sentence show the character acting/speaking (not remembered)?"""
        start, end, sentence = sentence_at(chapter.text, mention.start, self.spans(chapter))
        if not sentence or MEMORY_RE.search(sentence):
            return False, sentence, start
        line_start = chapter.text.rfind("\n", 0, mention.start) + 1
        line = chapter.text[line_start: chapter.text.find("\n", mention.start) if "\n" in chapter.text[mention.start:] else len(chapter.text)]
        if DIALOGUE_RE.match(line) and ACTION_RE.search(sentence):
            return True, sentence, start
        window = chapter.text[mention.end: min(end, mention.end + 60)]
        return bool(ACTION_RE.search(window)), sentence, start

    def _death_statements(self, chapter):
        result = []
        for mention in self.mentions(chapter):
            after = chapter.text[mention.end: mention.end + 40]
            before = chapter.text[max(0, mention.start - 25): mention.start]
            if re.match(DEATH_AFTER_NAME, after, re.IGNORECASE) or re.search(DEATH_BEFORE_NAME + r"$", before):
                start, end, sentence = sentence_at(chapter.text, mention.start, self.spans(chapter))
                if re.search(r"(?i:\bне\s+(?:загину|поме|вбит|убит))", sentence) or re.search(r"(?i:\bякби\b|\bмайже\b|\bледь не\b|\bмало не\b)", sentence):
                    continue
                if ATTEMPT_RE.search(sentence) and not DEFINITE_DEATH_RE.search(sentence):
                    continue  # "влила смертельну дозу отрути" — an attempt, the outcome is not stated
                result.append((mention, sentence))
        return result

    def _stated_ages(self, chapter):
        result = []
        for mention in self.mentions(chapter):
            after = chapter.text[mention.end: mention.end + 40]
            before = chapter.text[max(0, mention.start - 20): mention.start]
            m = AGE_AFTER_NAME.match(after) or AGE_BEFORE_NAME.search(before)
            if m:
                _, _, sentence = sentence_at(chapter.text, mention.start, self.spans(chapter))
                result.append((mention, int(m.group(1)), sentence))
        return result

    def _evidence(self, chapter, sentence):
        start, end, verified = _verified_quote(chapter.text, sentence[:400])
        quote = chapter.text[start:end] if verified else sentence[:400]
        return EvidenceDraft("chapter", chapter.id, chapter.title, quote, start, end, verified)

    # --- rules -----------------------------------------------------------------
    def dead_character_active(self):
        out = []
        for chapter in self.chapters:
            if chapter.is_flashback:
                continue
            reported = set()
            for mention in self.mentions(chapter):
                c = self.snap.character(mention.entity_id)
                if c is None or c.id in reported:
                    continue
                outcome = compare_points(chapter.story_time, c.death) if chapter.story_time.known else None
                by_chapter = False
                if not outcome and c.death_chapter and c.dead_in(chapter):
                    outcome, by_chapter = "likely", True  # the author set the chapter of the death
                if not outcome:
                    continue
                active, sentence, _ = self._is_active(chapter, mention)
                if not active:
                    continue
                reported.add(c.id)
                if chapter.narrator_unreliable:
                    category, severity = INSUFFICIENT, INFO
                else:
                    category, severity = {"violation": (POTENTIAL, WARNING), "likely": (POTENTIAL, WARNING), "borderline": (INSUFFICIENT, INFO)}[outcome]
                ev = self._evidence(chapter, sentence)
                out.append(FindingDraft(
                    rule="dead_character_active", category=category, severity=severity, source="text",
                    summary=f"{c.name} діє в розділі «{chapter.title}», хоча на цей час уже загинув(ла)",
                    explanation=(
                        (f"За енциклопедією персонаж загинув у розділі «{c.death_chapter[2]}». " if by_chapter else
                         f"Час розділу: {chapter.story_time.text()}; смерть персонажа: {c.death.text()}. ")
                        + "Якщо це спогад, сон або дія за правилом світу — позначте розділ як флешбек або відхиліть результат."
                        + (" Оповідач позначений як ненадійний." if chapter.narrator_unreliable else "")
                    ),
                    chapter_id=chapter.id, quote=ev.quote, start=ev.start, end=ev.end, quote_verified=ev.verified,
                    evidence=[ev, EvidenceDraft("character", c.id, c.name, verified=True)],
                    subject=(("character", c.id), ("chapter", chapter.id)),
                ))
        return out

    def death_then_alive(self):
        out = []
        deaths = {}  # character id -> (chapter, sentence)
        revived = set()
        for chapter in self.chapters:
            if REVIVAL_RE.search(chapter.text):
                for mention in self.mentions(chapter):
                    _, _, sentence = sentence_at(chapter.text, mention.start, self.spans(chapter))
                    if REVIVAL_RE.search(sentence):
                        revived.add(mention.entity_id)
            if not chapter.is_flashback:
                reported = set()
                for mention in self.mentions(chapter):
                    cid = mention.entity_id
                    if cid not in deaths or cid in revived or cid in reported:
                        continue
                    death_chapter, death_sentence = deaths[cid]
                    if death_chapter.id == chapter.id or death_chapter.book_id != chapter.book_id:
                        continue
                    active, sentence, _ = self._is_active(chapter, mention)
                    if not active:
                        continue
                    reported.add(cid)
                    c = self.snap.character(cid)
                    later = self._evidence(chapter, sentence)
                    earlier = self._evidence(death_chapter, death_sentence)
                    category, severity = (INSUFFICIENT, INFO) if chapter.narrator_unreliable or death_chapter.narrator_unreliable else (POTENTIAL, WARNING)
                    out.append(FindingDraft(
                        rule="death_then_alive", category=category, severity=severity, source="text",
                        summary=f"{c.name}: загибель у «{death_chapter.title}», але діє в «{chapter.title}»",
                        explanation=(
                            "У попередньому розділі описано смерть персонажа, а пізніше він(вона) говорить або діє, "
                            "без ознак спогаду, флешбеку чи воскресіння."
                        ),
                        chapter_id=chapter.id, quote=later.quote, start=later.start, end=later.end,
                        quote_verified=later.verified, evidence=[earlier, later],
                        subject=(("character", cid), ("chapter", chapter.id)),
                    ))
            for mention, sentence in self._death_statements(chapter):
                if mention.entity_id not in deaths and not chapter.is_flashback:
                    deaths[mention.entity_id] = (chapter, sentence)
        return out

    def ages(self):
        out = []
        stated = {}  # character id -> [(chapter, age, sentence)]
        for chapter in self.chapters:
            for mention, age, sentence in self._stated_ages(chapter):
                stated.setdefault(mention.entity_id, []).append((chapter, age, sentence))
        for cid, items in stated.items():
            c = self.snap.character(cid)
            if c is None:
                continue
            # Against the birth date.
            for chapter, age, sentence in items:
                if not (chapter.story_time.known and c.birth.known):
                    continue
                expected = chapter.story_time.key - c.birth.key
                tolerance = Decimal("1") + (c.birth.tolerance or 0) + (chapter.story_time.tolerance or 0)
                if abs(Decimal(age) - expected) > tolerance:
                    ev = self._evidence(chapter, sentence)
                    exact = c.birth.is_exact and chapter.story_time.is_exact
                    out.append(FindingDraft(
                        rule="age_mismatch", category=CONFIRMED if exact and ev.verified else POTENTIAL,
                        severity=ERROR if exact else WARNING, source="text",
                        summary=f"{c.name}: у тексті вік {age}, а за датою народження — близько {fmt_number(expected)}",
                        explanation=f"Народження: {c.birth.text()}; час розділу «{chapter.title}»: {chapter.story_time.text()}.",
                        chapter_id=chapter.id, quote=ev.quote, start=ev.start, end=ev.end, quote_verified=ev.verified,
                        evidence=[ev, EvidenceDraft("character", c.id, c.name, verified=True)],
                        subject=(("character", cid), ("chapter", chapter.id)),
                    ))
            # Between chapters (works without a birth date).
            dated = [(ch, age, s) for ch, age, s in items if ch.story_time.known]
            for i, (ch_a, age_a, s_a) in enumerate(dated):
                for ch_b, age_b, s_b in dated[i + 1:]:
                    time_gap = ch_b.story_time.key - ch_a.story_time.key
                    age_gap = Decimal(age_b - age_a)
                    tolerance = Decimal("1") + (ch_a.story_time.tolerance or 0) + (ch_b.story_time.tolerance or 0)
                    if abs(age_gap - time_gap) > tolerance:
                        ev_a, ev_b = self._evidence(ch_a, s_a), self._evidence(ch_b, s_b)
                        out.append(FindingDraft(
                            rule="age_inconsistent", category=POTENTIAL, severity=WARNING, source="text",
                            summary=f"{c.name}: вік у розділах «{ch_a.title}» і «{ch_b.title}» не узгоджується з часом між ними",
                            explanation=f"Вік {age_a} → {age_b}, але між розділами минуло {fmt_number(time_gap)}.",
                            chapter_id=ch_b.id, quote=ev_b.quote, start=ev_b.start, end=ev_b.end, quote_verified=ev_b.verified,
                            evidence=[ev_a, ev_b], subject=(("character", cid), ("chapter", ch_a.id), ("chapter", ch_b.id)),
                        ))
        return out

    def name_typos(self, chapters=None):
        """Capitalised words very close to a known name that are not a known form.

        A typo keeps the first letter and the length (±1); two swapped letters count as one slip. Short names
        allow one slip, long ones two — otherwise unrelated names match («Бартон», «Марина» → «Мартін»).
        """
        known = []
        for c in self.snap.characters:
            for name in c.names():
                for part in re.findall(r"[^\W\d_]{4,}", name):
                    known.append((c, part, stem(part)))
        out = []
        for chapter in chapters or self.chapters:
            covered = [(m.start, m.end) for m in self.mentions(chapter)]
            seen = set()
            for m in re.finditer(r"(?<![^\W\d_])[А-ЯІЇЄҐA-Z][^\W\d_]{3,}", chapter.text):
                word = m.group(0)
                if any(s <= m.start() < e for s, e in covered) or word in seen:
                    continue
                prev = chapter.text[max(0, m.start() - 3): m.start()]
                if not prev.strip() or re.search(r"[.!?…—\-\n]\s*$", prev):
                    continue  # sentence start: capitalisation is not a signal
                w_stem = stem(word)
                for c, part, p_stem in known:
                    if w_stem == p_stem or word.lower().startswith(p_stem):
                        break
                    limit = 1 if len(p_stem) <= 6 else 2
                    if w_stem[0] == p_stem[0] and abs(len(w_stem) - len(p_stem)) <= 1 and _distance(w_stem, p_stem, limit) <= limit:
                        seen.add(word)
                        _, _, sentence = sentence_at(chapter.text, m.start(), self.spans(chapter))
                        ev = self._evidence(chapter, sentence)
                        out.append(FindingDraft(
                            rule="possible_name_typo", category=POTENTIAL, severity=INFO, source="text",
                            summary=f"«{word}» схоже на імʼя «{part}» ({c.name})",
                            explanation="Можлива помилка в імені. Якщо це інша особа або нове імʼя — додайте його як альтернативне імʼя.",
                            chapter_id=chapter.id, quote=ev.quote, start=ev.start, end=ev.end, quote_verified=ev.verified,
                            evidence=[ev, EvidenceDraft("character", c.id, c.name, verified=True)],
                            subject=(("character", c.id), ("chapter", chapter.id), ("word", word)),
                        ))
                        break
        return out

    def run(self):
        return self.dead_character_active() + self.death_then_alive() + self.ages() + self.name_typos()


def _distance(a, b, limit):
    """Edit distance where two swapped neighbouring letters are one edit («Андресон» → «Андерсон»);
    returns ``limit + 1`` as soon as it is clearly over the limit."""
    if a == b:
        return 0
    before, previous = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            cost = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cost = min(cost, before[j - 2] + 1)
            current.append(cost)
        if min(current) > limit:
            return limit + 1
        before, previous = previous, current
    return previous[-1]


__all__ = ["ManuscriptAnalyzer", "OUTCOME_CATEGORY"]
