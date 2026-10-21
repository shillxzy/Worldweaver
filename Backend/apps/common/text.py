"""Small text helpers shared by documents, search and analysis."""
import re
import unicodedata

# Letters (incl. Ukrainian), digits and in-word apostrophes/hyphens.
WORD_RE = re.compile(r"[^\W_]+(?:['’ʼ\-][^\W_]+)*", re.UNICODE)
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "‘": "'"})
_QUOTES = str.maketrans({"«": '"', "»": '"', "„": '"', "“": '"', "”": '"'})
_DASHES = str.maketrans({"—": "-", "–": "-", "―": "-"})


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def normalize_for_match(text: str) -> str:
    """Normalize text so that quote verification tolerates typographic differences."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.translate(_APOSTROPHES).translate(_QUOTES).translate(_DASHES)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def find_quote(haystack: str, quote: str):
    """Return (start, end) of ``quote`` in ``haystack`` using tolerant matching, or None.

    Offsets refer to the original ``haystack``. Matching ignores case, whitespace runs,
    and typographic variants of quotes, apostrophes and dashes.
    """
    if not quote or not haystack:
        return None
    norm_quote = normalize_for_match(quote).strip(' ."')
    if len(norm_quote) < 3:
        return None
    # Build normalized haystack with an index map back to original offsets.
    chars, index_map = [], []
    prev_space = True
    for i, ch in enumerate(unicodedata.normalize("NFC", haystack)):
        c = ch.translate(_APOSTROPHES).translate(_QUOTES).translate(_DASHES).lower()
        if c.isspace():
            if prev_space:
                continue
            c = " "
            prev_space = True
        else:
            prev_space = False
        chars.append(c)
        index_map.append(i)
    norm_hay = "".join(chars)
    pos = norm_hay.find(norm_quote)
    if pos < 0:
        return None
    start = index_map[pos]
    end = index_map[pos + len(norm_quote) - 1] + 1
    return start, end
