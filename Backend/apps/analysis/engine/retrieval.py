"""Lexical retrieval of relevant world context for a manuscript fragment.

MVP ranking (no vector DB): an entry scores for
  * direct mentions of linked characters / factions in the fragment (strong signal),
  * its title appearing in the fragment,
  * tag overlap with fragment terms,
  * shared rare-ish terms (stem overlap weighted by inverse document frequency).
Only the top entries within a character budget are returned, never the whole lore.
"""
import math
import re
from collections import Counter

from .mentions import MentionMatcher, stem

TOKEN_RE = re.compile(r"[^\W\d_]{4,}")
STOP = {"який", "яка", "яке", "які", "цей", "ця", "це", "ці", "того", "тому", "його", "її", "їхній", "свій", "своя",
        "було", "були", "буде", "бути", "коли", "тоді", "тепер", "також", "тільки", "лише", "щоб", "через", "після",
        "перед", "між", "під", "над", "біля", "навіть", "майже", "дуже", "вона", "вони", "воно", "мене", "тебе", "нього"}


def terms(text):
    return [stem(t) for t in TOKEN_RE.findall(text.lower()) if t not in STOP]


def build_context(snapshot, fragment, budget_chars=4000, max_entries=8):
    """Return {"characters": [...], "lore": [...], "events": [...]} ordered by relevance."""
    matcher = MentionMatcher([(c.id, c.names()) for c in snapshot.characters])
    mentioned_chars = {m.entity_id for m in matcher.find(fragment)}
    faction_matcher = MentionMatcher([(f.id, [f.name]) for f in snapshot.factions])
    mentioned_factions = {m.entity_id for m in faction_matcher.find(fragment)}

    fragment_terms = Counter(terms(fragment))
    docs = [(entry, Counter(terms(entry.title + " " + entry.content))) for entry in snapshot.lore]
    df = Counter()
    for _, counts in docs:
        df.update(set(counts))
    n_docs = max(1, len(docs))

    scored = []
    for entry, counts in docs:
        score = 0.0
        title_stem = " ".join(terms(entry.title))
        if title_stem and title_stem in " ".join(fragment_terms):
            score += 5
        score += 2 * len({stem(t) for t in entry.tags} & set(fragment_terms))
        for term in set(counts) & set(fragment_terms):
            score += math.log(1 + n_docs / df[term])
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], x[1].id))

    characters = [c for c in snapshot.characters if c.id in mentioned_chars]
    events = [
        e for e in snapshot.events
        if any(cid in mentioned_chars for cid, _ in e.participants)
    ][:10]
    lore, used = [], 0
    for score, entry in scored[:max_entries * 2]:
        snippet = entry.content[:1200]
        if used + len(snippet) > budget_chars:
            continue
        lore.append({"entry": entry, "score": round(score, 3), "snippet": snippet})
        used += len(snippet)
        if len(lore) >= max_entries:
            break
    return {
        "characters": characters,
        "factions": [f for f in snapshot.factions if f.id in mentioned_factions],
        "events": events,
        "lore": lore,
    }
