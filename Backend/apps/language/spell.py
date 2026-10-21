"""Ukrainian spellchecking, independent of the plot analyser.

Backend: Hunspell dictionary (``uk_UA.aff`` / ``uk_UA.dic``) read by ``spylls`` (pure Python).
The LibreOffice uk_UA dictionary (MPL 1.1, based on brown-uk/dict_uk) is the tested source.
Without dictionary files the service reports itself unavailable — it never guesses norms.

Two separate result kinds:
* ``spelling`` – the word is not in the dictionary (author may accept a suggestion,
  reject it, or add the word to their dictionary);
* ``style``    – typographic recommendations (repeated word, double space, hyphen used as
  a dash, missing space after punctuation). These are hints, not normative rules.

No claim of conformity with a particular edition of «Український правопис» is made: the
result is exactly as good as the dictionary in use.
"""
import functools
import logging
import re
import threading

from django.conf import settings

logger = logging.getLogger("worldweaver.language")

WORD_RE = re.compile(r"[^\W\d_]+(?:['’ʼ`\-][^\W\d_]+)*", re.UNICODE)
APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'"})
STYLE_RULES = [
    ("repeated_word", re.compile(r"(?i)(?<![^\W\d_])([^\W\d_]{2,})\s+\1(?![^\W\d_])"), "Повтор слова підряд."),
    ("double_space", re.compile(r"(?<=\S) {2,}(?=\S)"), "Подвійний пробіл."),
    ("hyphen_as_dash", re.compile(r"(?<=\s)-(?=\s)"), "Між словами зазвичай ставлять тире (—), а не дефіс."),
    ("space_after_punct", re.compile(r"(?<=[^\W\d_])[,;:](?=[^\W\d_])"), "Після розділового знака бракує пробілу."),
    ("space_before_punct", re.compile(r"(?<=[^\W\d_]) +(?=[,.;:!?])"), "Зайвий пробіл перед розділовим знаком."),
]
MAX_SPELLING_ISSUES = 300


class SpellUnavailable(Exception):
    pass


class SpellService:
    _lock = threading.Lock()
    _dictionary = None
    _load_error = None

    @classmethod
    def dictionary(cls):
        if cls._dictionary is None and cls._load_error is None:
            with cls._lock:
                if cls._dictionary is None and cls._load_error is None:
                    base = settings.SPELL_DICT_DIR / "uk_UA"
                    if not (base.with_suffix(".aff").exists() and base.with_suffix(".dic").exists()):
                        cls._load_error = "Словник uk_UA не знайдено в SPELL_DICT_DIR."
                    else:
                        try:
                            from spylls.hunspell import Dictionary

                            cls._dictionary = Dictionary.from_files(str(base))
                        except Exception as exc:  # noqa: BLE001 — broken dictionary files must not crash the API
                            logger.error("Failed to load dictionary: %s", type(exc).__name__)
                            cls._load_error = "Не вдалося завантажити словник."
        if cls._dictionary is None:
            raise SpellUnavailable(cls._load_error)
        return cls._dictionary

    @classmethod
    def status(cls):
        try:
            cls.dictionary()
            return {"available": True, "dictionary": "uk_UA (Hunspell)", "error": None}
        except SpellUnavailable as exc:
            return {"available": False, "dictionary": None, "error": str(exc)}

    @classmethod
    def is_correct(cls, word):
        d = cls.dictionary()
        normalized = word.translate(APOSTROPHES)
        return d.lookup(word) or d.lookup(normalized) or d.lookup(normalized.lower())

    @staticmethod
    @functools.lru_cache(maxsize=4096)
    def suggest(word):
        d = SpellService.dictionary()
        return [s for s in d.suggest(word.translate(APOSTROPHES))][:6]

    @classmethod
    def check(cls, text, accepted_words=()):
        """Return {"spelling": [...], "style": [...]} with character offsets into ``text``."""
        accepted = {w.translate(APOSTROPHES).lower() for w in accepted_words}
        spelling = []
        cache = {}
        for m in WORD_RE.finditer(text):
            word = m.group(0)
            if len(word) < 2 or word.isupper() or word.translate(APOSTROPHES).lower() in accepted:
                continue
            if word not in cache:
                parts = [p for p in re.split(r"-", word) if p]
                cache[word] = cls.is_correct(word) or (len(parts) > 1 and all(cls.is_correct(p) or p.lower() in accepted for p in parts))
            if not cache[word]:
                spelling.append({"kind": "spelling", "word": word, "start": m.start(), "end": m.end(), "message": "Слова немає у словнику."})
                if len(spelling) >= MAX_SPELLING_ISSUES:
                    break
        style = []
        for code, pattern, message in STYLE_RULES:
            for m in pattern.finditer(text):
                style.append({"kind": "style", "rule": code, "start": m.start(), "end": m.end(), "text": m.group(0), "message": message})
        style.sort(key=lambda s: s["start"])
        return {"spelling": spelling, "style": style}


def world_vocabulary(world):
    """Names and terms of a world are accepted automatically (fantasy names are not typos)."""
    if world is None:
        return set()
    words = set()
    for name, aliases in world.characters.values_list("name", "aliases"):
        for value in [name, *(aliases or [])]:
            words.update(w.lower() for w in WORD_RE.findall(str(value)))
    for value in [*world.factions.values_list("name", flat=True), *world.lore_entries.values_list("title", flat=True), world.name]:
        words.update(w.lower() for w in WORD_RE.findall(value))
    return words
