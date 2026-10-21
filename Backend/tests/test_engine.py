from decimal import Decimal as D

import pytest

from apps.analysis.engine.chunking import split_text
from apps.analysis.engine.evaluation import evaluate
from apps.analysis.engine.graph import CycleError, Graph
from apps.analysis.engine.mentions import MentionMatcher
from apps.analysis.engine.retrieval import build_context
from apps.analysis.engine.rules import run_world_rules
from apps.analysis.engine.types import (
    APPROXIMATE,
    CharacterS,
    EventS,
    LoreS,
    MembershipS,
    RelationshipS,
    TimePoint,
    WorldSnapshot,
    compare_points,
)
from apps.common.text import count_words, find_quote


def tp(v, precision="exact", unc=0):
    return TimePoint(D(str(v)), precision, D(str(unc)))


def test_graph_paths_cycles_and_topological_sort():
    g = Graph()
    for a, b in [(1, 2), (2, 3), (1, 4)]:
        g.add_edge(a, b)
    assert g.find_path(1, 3) == [1, 2, 3]
    assert g.find_path(3, 1) is None
    assert g.find_path(3, 1, directed=False) == [3, 2, 1]
    assert sorted(g.neighbors(2)) == [1, 3]
    assert g.topological_sort() == [1, 2, 3, 4] or g.topological_sort().index(1) == 0
    assert g.find_cycle() is None
    assert g.would_create_cycle(3, 1) and not g.would_create_cycle(4, 3)
    g.add_edge(3, 1)
    cycle = g.find_cycle()
    assert cycle[0] == cycle[-1] and set(cycle) == {1, 2, 3}
    with pytest.raises(CycleError) as exc:
        g.topological_sort()
    assert set(exc.value.cycle) == {1, 2, 3}


def test_compare_points_respects_uncertainty_and_unknown():
    assert compare_points(tp(10), tp(5)) == "violation"
    assert compare_points(tp(10, APPROXIMATE, 1), tp(5)) == "likely"
    assert compare_points(tp(6, APPROXIMATE, 2), tp(5)) == "borderline"
    assert compare_points(TimePoint(None, "unknown"), tp(5)) is None
    assert compare_points(tp(5), tp(5)) is None


def test_world_rules_detect_formal_contradictions():
    snap = WorldSnapshot(
        characters=[
            CharacterS(1, "Каель", birth=tp(300), death=tp(340), status="alive"),
            CharacterS(2, "Ейра", birth=tp(330), death=tp(320)),
        ],
        events=[EventS(1, "Облога", tp(350), participants=[(1, "participant")]), EventS(2, "Свято", tp(10), end=tp(5))],
        memberships=[MembershipS(1, 1, 9, start=tp(290))],
        relationships=[RelationshipS(1, "alliance", ("faction", 1), ("faction", 2)), RelationshipS(2, "enmity", ("faction", 2), ("faction", 1))],
    )
    rules = {f.rule for f in run_world_rules(snap)}
    assert {"status_conflict", "death_before_birth", "event_after_death", "event_end_before_start", "membership_before_birth", "relationship_conflict"} <= rules


def test_unknown_dates_are_not_errors():
    snap = WorldSnapshot(
        characters=[CharacterS(1, "Каель")],
        events=[EventS(1, "Облога", TimePoint(None, "unknown"), participants=[(1, "participant")])],
    )
    assert run_world_rules(snap) == []


def test_mentions_handle_inflection_aliases_and_honorifics():
    matcher = MentionMatcher([(1, ["Ейра Вальмонт", "Картографка"]), (2, ["Каель"]), (3, ["Доктор Лео Март"])])
    text = "Каеля не було. Ейрою пишалися. Пані Вальмонт сказала. Доктор пішов. Лео Мартом звали лікаря. Картографки нема."
    found = {(m.entity_id, m.text) for m in matcher.find(text)}
    assert (2, "Каеля") in found and (1, "Ейрою") in found and (1, "Вальмонт") in found
    assert (3, "Лео Мартом") in found and (1, "Картографки") in found
    assert not any(m.text == "Доктор" for m in matcher.find(text))


def test_find_quote_tolerates_typography():
    text = "Вона сказала: «Пам’ять —  це море»."
    span = find_quote(text, 'памʼять - це море')
    assert span and text[span[0]:span[1]] == "Пам’ять —  це море"
    assert find_quote(text, "вигадана цитата") is None
    assert count_words("Пам’ять — це море, а 3 кораблі — пів-світу.") == 7


def test_chunking_overlap_and_coverage():
    text = "\n\n".join(f"Абзац {i}. " + "слово " * 80 for i in range(30))
    chunks = split_text(text, 1, max_chars=1500, overlap=200)
    assert len(chunks) > 3
    assert chunks[0].start == 0 and chunks[-1].end == len(text)
    for a, b in zip(chunks, chunks[1:]):
        assert b.start < a.end  # overlap
        assert text[b.start:b.end] == b.text


def test_retrieval_returns_relevant_lore_within_budget():
    snap = WorldSnapshot(
        characters=[CharacterS(1, "Ейра")],
        lore=[
            LoreS(1, "Перлина Сяйва", "Перлина світиться лише під водою і гасне на суші.", "item", ["світло"]),
            LoreS(2, "Кухня", "Рецепти пирогів із ягодами.", "culture"),
            LoreS(3, "Безодня", "Безодня — найглибша западина океану, де живе Левіафан.", "geography"),
        ],
    )
    ctx = build_context(snap, "Ейра тримала перлину на суші, і вона світилася.", budget_chars=200)
    titles = [item["entry"].title for item in ctx["lore"]]
    assert titles[0] == "Перлина Сяйва" and "Кухня" not in titles
    assert sum(len(i["snippet"]) for i in ctx["lore"]) <= 200
    assert [c.name for c in ctx["characters"]] == ["Ейра"]


def test_evaluation_metrics_are_computed_from_results():
    result = evaluate()
    assert result["tp"] + result["fn"] > 0
    assert 0 <= result["precision"] <= 1 and 0 <= result["recall"] <= 1
    expected_f1 = 2 * result["precision"] * result["recall"] / (result["precision"] + result["recall"])
    assert abs(result["f1"] - expected_f1) < 1e-3
    # Known-hard cases must stay labelled honestly (they are expected misses today).
    hard = {row["case"]: row for row in result["cases"] if row["case"].startswith("hard_")}
    assert hard["hard_paraphrased_death"]["fn"] == 1
    assert result["quote_verified_share"] == 1.0
    # All non-hard cases pass.
    assert all(r["fp"] == 0 and r["fn"] == 0 and r["insufficient_ok"] for r in result["cases"] if not r["case"].startswith("hard_"))
