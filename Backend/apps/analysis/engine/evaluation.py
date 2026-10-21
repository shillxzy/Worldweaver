"""Labelled control set for the deterministic consistency engine + metric computation.

Each case is a small in-memory world with an explicit set of expected findings,
identified as ``(rule, subject)``. A prediction counts as positive when its category is
"confirmed" or "potential"; "insufficient_data" results are reported separately and are
never counted as positives (they mean "cannot decide").

Metrics are computed from the actual engine output — nothing here is hard-coded.
"""
import time
from dataclasses import dataclass, field
from decimal import Decimal as D

from .manuscript import ManuscriptAnalyzer
from .rules import run_world_rules
from .types import (
    APPROXIMATE,
    CONFIRMED,
    EXACT,
    INSUFFICIENT,
    POTENTIAL,
    ChapterS,
    CharacterS,
    DependencyS,
    EventS,
    RelationshipS,
    TimePoint,
    WorldSnapshot,
)


def tp(key, precision=EXACT, unc=0):
    return TimePoint(D(str(key)), precision, D(str(unc)))


@dataclass
class Case:
    name: str
    description: str
    snapshot: WorldSnapshot
    expected: set = field(default_factory=set)
    expect_insufficient: bool = False


def _kael(**kw):
    return CharacterS(1, "Каель", **kw)


def _eira(**kw):
    return CharacterS(2, "Ейра Вальмонт", aliases=["Ейра"], **kw)


def build_cases():
    cases = []

    cases.append(Case(
        "real_contradiction_cross_chapter",
        "Персонаж гине в розділі 1 і говорить у розділі 3 без пояснень.",
        WorldSnapshot(characters=[_kael(), _eira()], chapters=[
            ChapterS(10, "Розділ 1", 1, "Бій тривав до ночі. Каель загинув біля воріт, захищаючи Ейру."),
            ChapterS(11, "Розділ 2", 2, "Ейра довго мовчала. Вона не могла повірити в те, що сталося."),
            ChapterS(12, "Розділ 3", 3, "— Ходімо, — сказав Каель і рушив до брами."),
        ]),
        expected={("death_then_alive", ("character", 1))},
    ))

    cases.append(Case(
        "consistent_event",
        "Персонаж бере участь у події між народженням і смертю.",
        WorldSnapshot(
            characters=[_kael(birth=tp(300), death=tp(360), status="dead")],
            events=[EventS(1, "Облога Берега Тиші", tp(340), participants=[(1, "participant")])],
        ),
    ))

    cases.append(Case(
        "flashback",
        "Розділ-флешбек і спогад після смерті персонажа не є суперечністю.",
        WorldSnapshot(characters=[_kael(death=tp(340)), _eira()], chapters=[
            ChapterS(20, "Загибель", 1, "Каель загинув у шторм, і море забрало його човен."),
            ChapterS(21, "Колись давно", 2, "— Я повернуся, — сказав Каель, усміхаючись.", is_flashback=True, story_time=tp(330)),
            ChapterS(22, "Після", 3, "Ейра згадала, як Каель сміявся над її картами.", story_time=tp(345)),
        ]),
    ))

    cases.append(Case(
        "unreliable_narrator",
        "Ненадійний оповідач бачить загиблого — результат лише «недостатньо даних».",
        WorldSnapshot(characters=[_kael(death=tp(340))], chapters=[
            ChapterS(30, "Марення", 1, "Каель кивнув мені з іншого берега річки.", story_time=tp(350), narrator_unreliable=True),
        ]),
        expect_insufficient=True,
    ))

    cases.append(Case(
        "name_change_false_positive",
        "Персонаж називається альтернативним іменем; це не помилка в імені й не новий персонаж.",
        WorldSnapshot(characters=[CharacterS(3, "Мірела", aliases=["Міра", "Тінь"]), CharacterS(4, "Марек")], chapters=[
            ChapterS(40, "Маски", 1, "Того вечора Міра усміхнулася. Потім Тінь сказала Мареку, що час іти."),
        ]),
    ))

    cases.append(Case(
        "approximate_date_borderline",
        "Приблизна дата події (≈100 ±5) і народження в 102 році: суперечність не доведена.",
        WorldSnapshot(
            characters=[_kael(birth=tp(102))],
            events=[EventS(2, "Перший похід", tp(100, APPROXIMATE, 5), participants=[(1, "participant")])],
        ),
        expect_insufficient=True,
    ))

    cases.append(Case(
        "approximate_date_far",
        "Подія ≈100 (±2), персонаж народився у 120 — імовірна суперечність навіть з урахуванням похибки.",
        WorldSnapshot(
            characters=[_kael(birth=tp(120))],
            events=[EventS(3, "Перший похід", tp(100, APPROXIMATE, 2), participants=[(1, "participant")])],
        ),
        expected={("event_before_birth", ("character", 1))},
    ))

    cases.append(Case(
        "unknown_age",
        "Вік персонажа невідомий: заява про вік у тексті не є помилкою.",
        WorldSnapshot(characters=[_kael()], chapters=[
            ChapterS(50, "Порт", 1, "Каелю було 30 років, коли він уперше побачив порт.", story_time=tp(340)),
        ]),
    ))

    cases.append(Case(
        "magic_rule_explained",
        "Загиблий персонаж бере участь у події як дух (роль «посмертно»).",
        WorldSnapshot(
            characters=[_kael(death=tp(50), status="dead")],
            events=[EventS(4, "Явлення духа", tp(60), participants=[(1, "posthumous")])],
        ),
    ))

    cases.append(Case(
        "event_after_death",
        "Загиблий персонаж бере участь у події як звичайний учасник.",
        WorldSnapshot(
            characters=[_kael(death=tp(50), status="dead")],
            events=[EventS(5, "Битва при скелях", tp(60), participants=[(1, "participant")])],
        ),
        expected={("event_after_death", ("character", 1))},
    ))

    cases.append(Case(
        "cross_chapter_ages",
        "Вік у двох розділах не узгоджується з часом між ними (суперечність видно лише при зіставленні).",
        WorldSnapshot(characters=[_eira()], chapters=[
            ChapterS(60, "Весна", 1, "Того року Ейрі було 20 років.", story_time=tp(340)),
            ChapterS(61, "Осінь", 2, "Тепер Ейрі було 30 років.", story_time=tp(345)),
        ]),
        expected={("age_inconsistent", ("character", 2))},
    ))

    cases.append(Case(
        "age_vs_birth",
        "Вік у тексті суперечить даті народження.",
        WorldSnapshot(characters=[_eira(birth=tp(320))], chapters=[
            ChapterS(70, "Свято", 1, "На святі Ейрі було 25 років.", story_time=tp(340)),
        ]),
        expected={("age_mismatch", ("character", 2))},
    ))

    cases.append(Case(
        "negated_death",
        "«Каель не загинув» — не опис смерті.",
        WorldSnapshot(characters=[_kael()], chapters=[
            ChapterS(80, "Звістка", 1, "На щастя, Каель не загинув у тій битві."),
            ChapterS(81, "Зустріч", 2, "— Я тут, — сказав Каель."),
        ]),
    ))

    cases.append(Case(
        "resurrection",
        "Персонаж гине, потім воскресає за правилом світу, потім говорить.",
        WorldSnapshot(characters=[_kael()], chapters=[
            ChapterS(90, "Кінець", 1, "Каель загинув на світанку."),
            ChapterS(91, "Ритуал", 2, "Жриці співали всю ніч, і Каель воскрес."),
            ChapterS(92, "Дорога", 3, "— Рушаймо, — сказав Каель."),
        ]),
    ))

    cases.append(Case(
        "dead_character_active_by_time",
        "Час розділу пізніший за смерть персонажа, і персонаж діє.",
        WorldSnapshot(characters=[_kael(death=tp(340))], chapters=[
            ChapterS(100, "Після шторму", 1, "Каель кивнув і відчинив двері.", story_time=tp(345)),
        ]),
        expected={("dead_character_active", ("character", 1))},
    ))

    cases.append(Case(
        "name_typo",
        "Описка в прізвищі посеред речення («Вальмнот» замість «Вальмонт»).",
        WorldSnapshot(characters=[_eira()], chapters=[
            ChapterS(110, "Карта", 1, "Того ранку пані Вальмнот розгорнула стару карту."),
        ]),
        expected={("possible_name_typo", ("character", 2))},
    ))

    cases.append(Case(
        "transitive_dependency",
        "A має бути раніше B, B — раніше C; дата C раніша за A (B без дати).",
        WorldSnapshot(
            events=[EventS(6, "Заснування", tp(100)), EventS(7, "Розкол", TimePoint(None, "unknown")), EventS(8, "Війна", tp(90))],
            dependencies=[DependencyS(1, 6, 7), DependencyS(2, 7, 8)],
        ),
        expected={("dependency_violated", ("event", 6))},
    ))

    cases.append(Case(
        "vocative_is_not_typo",
        "Кличний відмінок імені («Ейро!») — не описка.",
        WorldSnapshot(characters=[_eira()], chapters=[
            ChapterS(111, "Поклик", 1, "Він гукнув: «Ейро, зачекай!» — але вона не обернулася."),
        ]),
    ))

    cases.append(Case(
        "alliance_and_war",
        "Союз і ворожнеча тих самих фракцій у періоди, що перетинаються.",
        WorldSnapshot(relationships=[
            RelationshipS(1, "alliance", ("faction", 1), ("faction", 2), tp(100), tp(200)),
            RelationshipS(2, "enmity", ("faction", 1), ("faction", 2), tp(150), tp(160)),
        ]),
        expected={("relationship_conflict", ("faction", 1))},
    ))

    cases.append(Case(
        "alliance_then_war",
        "Союз, а потім війна у різні періоди — не суперечність.",
        WorldSnapshot(relationships=[
            RelationshipS(3, "alliance", ("faction", 1), ("faction", 2), tp(100), tp(120)),
            RelationshipS(4, "enmity", ("faction", 1), ("faction", 2), tp(130), tp(160)),
        ]),
    ))
    # --- hard cases: known limitations, labelled with the TRUE answer --------------------
    cases.append(Case(
        "hard_paraphrased_death",
        "Смерть описана перифразом («серце зупинилося назавжди»), потім персонаж говорить. "
        "Справжня суперечність; лексичні правила її не бачать.",
        WorldSnapshot(characters=[_kael()], chapters=[
            ChapterS(120, "Тиша", 1, "Того вечора серце Каеля зупинилося назавжди."),
            ChapterS(121, "Ранок", 2, "— Пора, — сказав Каель."),
        ]),
        expected={("death_then_alive", ("character", 1))},
    ))

    cases.append(Case(
        "hard_homonym_name",
        "Персонажка «Нова» загинула; пізніше слово «Нова» на початку репліки — звичайний прикметник. "
        "Суперечності немає, але збіг форми слова дає хибне спрацьовування.",
        WorldSnapshot(characters=[CharacterS(5, "Нова")], chapters=[
            ChapterS(130, "Палата", 1, "Нова загинула вночі в Палаті №7."),
            ChapterS(131, "Склад", 2, "— Нова партія прибула, — сказав капітан."),
        ]),
    ))
    return cases


def predict(snapshot):
    return run_world_rules(snapshot) + ManuscriptAnalyzer(snapshot).run()


def evaluate(cases=None):
    cases = cases or build_cases()
    total_tp = total_fp = total_fn = 0
    rows = []
    quotes_total = quotes_verified = 0
    started = time.perf_counter()
    for case in cases:
        t0 = time.perf_counter()
        findings = predict(case.snapshot)
        elapsed = time.perf_counter() - t0
        positives = {(f.rule, f.subject[0]) for f in findings if f.category in (CONFIRMED, POTENTIAL) and f.subject}
        insufficient = [f for f in findings if f.category == INSUFFICIENT]
        for f in findings:
            if f.quote:
                quotes_total += 1
                quotes_verified += int(f.quote_verified)
        tp_ = len(positives & case.expected)
        fp_ = len(positives - case.expected)
        fn_ = len(case.expected - positives)
        total_tp += tp_
        total_fp += fp_
        total_fn += fn_
        rows.append({
            "case": case.name, "description": case.description, "expected": sorted(map(str, case.expected)),
            "predicted": sorted(map(str, positives)), "tp": tp_, "fp": fp_, "fn": fn_,
            "insufficient": len(insufficient), "insufficient_ok": (len(insufficient) > 0) == case.expect_insufficient,
            "ms": round(elapsed * 1000, 2),
        })
    precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else 1.0
    recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "cases": rows,
        "tp": total_tp, "fp": total_fp, "fn": total_fn,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "total_ms": round((time.perf_counter() - started) * 1000, 2),
        "quotes_total": quotes_total, "quotes_verified": quotes_verified,
        "quote_verified_share": round(quotes_verified / quotes_total, 4) if quotes_total else None,
    }
