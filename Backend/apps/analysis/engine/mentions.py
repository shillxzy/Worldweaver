"""Finding mentions of characters (and other named entities) in Ukrainian text.

Ukrainian names inflect (Ейра → Ейри, Ейрою; Каель → Каеля, Каелем), so each name part is
reduced to a stem and matched with a closed set of case endings. Matching is
case-sensitive on the first letter to avoid hits on common words. Name parts shared
between several characters (e.g. a family name) are ambiguous and only count as part of a
full-name match. Honorifics such as «Доктор» are ignored.

Known limitations (documented, measured in the evaluation set): homonyms of common words
at the start of a sentence (e.g. a character named «Нова») and irregular alternations
(«Ольга» → «Ользі») are not fully handled.
"""
import re
from dataclasses import dataclass

VOWEL_ENDINGS = "аяоеєиіїйуюь"
CASE_ENDINGS = sorted(
    {"", "а", "я", "у", "ю", "і", "ї", "е", "є", "о", "и", "ь", "й", "ою", "єю", "ею", "ові", "еві", "єві",
     "ом", "ем", "єм", "ах", "ях", "ам", "ям", "ами", "ями", "ів", "їв", "ой", "ий", "ого", "ому", "им", "ім"},
    key=len, reverse=True,
)
HONORIFICS = {"доктор", "докторка", "капітан", "капітанка", "пан", "пані", "лорд", "леді", "король", "королева",
              "сер", "майстер", "отець", "брат", "сестра", "мати", "матір", "батько", "князь", "княгиня", "генерал",
              "командор", "професор", "професорка", "магістр", "лейтенант", "сержант", "дон", "донна", "старий", "стара"}
WORD_CHARS = r"[^\W\d_]"
SENTENCE_RE = re.compile(r"[^.!?…\n]+(?:[.!?…]+[»\"”]?|\n|$)", re.UNICODE)


def stem(word):
    lower = word.lower()
    if len(lower) > 3 and lower[-1] in VOWEL_ENDINGS:
        lower = lower[:-1]
        if len(lower) > 3 and lower[-1] in VOWEL_ENDINGS:
            lower = lower[:-1]
    return lower


def _form_pattern(word):
    """Regex for all inflected forms of one name word (first letter case-sensitive)."""
    s = stem(word)
    first, rest = s[0], s[1:]
    endings = "|".join(re.escape(e) for e in CASE_ENDINGS if e)
    return (
        rf"(?<!{WORD_CHARS})[{re.escape(first.upper())}]"
        rf"(?i:{re.escape(rest)}(?:{endings})?)(?!{WORD_CHARS})"
    )


def name_parts(name):
    return [p for p in re.findall(r"[^\W\d_]+(?:['’ʼ-][^\W\d_]+)*", name) if len(p) >= 3 and p.lower() not in HONORIFICS]


@dataclass
class Mention:
    entity_id: int
    start: int
    end: int
    text: str


class MentionMatcher:
    """Compiles patterns for a set of entities: ``entities`` = [(id, [name, alias, ...])]."""

    def __init__(self, entities):
        part_owners = {}
        for entity_id, names in entities:
            for name in names:
                for part in name_parts(name):
                    part_owners.setdefault(stem(part), set()).add(entity_id)
        self._patterns = []
        for entity_id, names in entities:
            alternatives = []
            for name in sorted(set(names), key=len, reverse=True):
                parts = name_parts(name)
                if not parts:
                    continue
                if len(parts) > 1:
                    alternatives.append(r"\s+".join(_form_pattern(p) for p in parts))
                for part in parts:
                    if part_owners.get(stem(part)) == {entity_id}:
                        alternatives.append(_form_pattern(part))
            if alternatives:
                self._patterns.append((entity_id, re.compile("|".join(f"(?:{a})" for a in alternatives))))

    def find(self, text):
        mentions = []
        for entity_id, pattern in self._patterns:
            for m in pattern.finditer(text):
                mentions.append(Mention(entity_id, m.start(), m.end(), m.group(0)))
        mentions.sort(key=lambda m: (m.start, -(m.end - m.start)))
        # Drop mentions fully covered by a longer earlier one (e.g. "Ейра Вальмонт" vs "Ейра").
        result, last_end = [], -1
        for mention in mentions:
            if mention.start >= last_end:
                result.append(mention)
                last_end = mention.end
        return result

    def known_stems(self):
        return {p.pattern for _, p in self._patterns}


def sentences(text):
    """Yield (start, end, sentence) spans."""
    for m in SENTENCE_RE.finditer(text):
        raw = m.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        start = m.start() + (len(raw) - len(raw.lstrip()))
        yield start, start + len(stripped), stripped


def sentence_at(text, position, spans=None):
    for start, end, sentence in spans or sentences(text):
        if start <= position < end:
            return start, end, sentence
    return position, position, ""
