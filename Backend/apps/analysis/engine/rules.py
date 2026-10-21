"""Deterministic world-level consistency rules.

Every rule is a pure function ``rule(snapshot) -> list[FindingDraft]``. Rules never treat
unknown data as an error: if a date is missing the check is skipped, and approximate
dates are compared with their uncertainty (see ``types.compare_points``).
"""
from decimal import Decimal

from .graph import CycleError, Graph
from .types import (
    CONFIRMED,
    ERROR,
    INFO,
    OUTCOME_CATEGORY,
    POTENTIAL,
    WARNING,
    EvidenceDraft,
    FindingDraft,
    TimePoint,
    compare_points,
    fmt_number,
)

PARTICIPANT = "participant"


def _ev(event):
    return EvidenceDraft("event", event.id, event.title, verified=True)


def _ch(character):
    return EvidenceDraft("character", character.id, character.name, verified=True)


def rule_event_end_before_start(snap):
    out = []
    for event in snap.events:
        outcome = compare_points(event.start, event.end)
        if outcome:
            category, severity = OUTCOME_CATEGORY[outcome]
            out.append(FindingDraft(
                rule="event_end_before_start", category=category, severity=severity,
                summary=f"Подія «{event.title}» завершується раніше, ніж починається",
                explanation=f"Початок: {event.start.text()}, завершення: {event.end.text()}.",
                evidence=[_ev(event)], subject=(("event", event.id),),
            ))
    return out


def rule_death_before_birth(snap):
    out = []
    for c in snap.characters:
        outcome = compare_points(c.birth, c.death)
        if outcome:
            category, severity = OUTCOME_CATEGORY[outcome]
            out.append(FindingDraft(
                rule="death_before_birth", category=category, severity=severity,
                summary=f"{c.name}: дата смерті раніша за дату народження",
                explanation=f"Народження: {c.birth.text()}, смерть: {c.death.text()}.",
                evidence=[_ch(c)], subject=(("character", c.id),),
            ))
    return out


def rule_status_conflict(snap):
    out = []
    for c in snap.characters:
        if c.status == "alive" and c.death.known:
            out.append(FindingDraft(
                rule="status_conflict", category=CONFIRMED, severity=WARNING,
                summary=f"{c.name}: статус «живий», але вказано дату смерті",
                explanation=f"Дата смерті: {c.death.text()}. Оновіть статус або приберіть дату.",
                evidence=[_ch(c)], subject=(("character", c.id),),
            ))
    return out


def rule_event_vs_lifetime(snap):
    """A character actively participates in an event before birth or after death.

    Participations with role 'mentioned' or 'posthumous' (e.g. explained by a world rule:
    ghosts, resurrection, prophecy) are intentionally skipped.
    """
    out = []
    for event in snap.events:
        for character_id, role in event.participants:
            if role != PARTICIPANT:
                continue
            c = snap.character(character_id)
            if c is None:
                continue
            # The event (its end, if any) happens before the character was born.
            before_birth = compare_points(c.birth, event.span_end)
            if before_birth:
                category, severity = OUTCOME_CATEGORY[before_birth]
                out.append(FindingDraft(
                    rule="event_before_birth", category=category, severity=severity,
                    summary=f"{c.name} бере участь у події «{event.title}» до свого народження",
                    explanation=f"Подія: {event.span_end.text()}; народження персонажа: {c.birth.text()}.",
                    evidence=[_ch(c), _ev(event)], subject=(("character", c.id), ("event", event.id)),
                ))
            after_death = compare_points(event.start, c.death)
            if after_death:
                category, severity = OUTCOME_CATEGORY[after_death]
                out.append(FindingDraft(
                    rule="event_after_death", category=category, severity=severity,
                    summary=f"{c.name} бере участь у події «{event.title}» після своєї смерті",
                    explanation=(
                        f"Подія: {event.start.text()}; смерть персонажа: {c.death.text()}. Якщо це пояснюється "
                        "правилом світу (спогад, дух, воскресіння), позначте участь як «посмертно»."
                    ),
                    evidence=[_ch(c), _ev(event)], subject=(("character", c.id), ("event", event.id)),
                ))
    return out


def rule_membership_vs_lifetime(snap):
    out = []
    for m in snap.memberships:
        c = snap.character(m.character_id)
        faction = snap.faction(m.faction_id)
        if c is None:
            continue
        fname = faction.name if faction else f"#{m.faction_id}"
        checks = [
            (compare_points(m.start, m.end), "membership_end_before_start", f"{c.name}: членство у «{fname}» завершується до початку"),
            (compare_points(c.birth, m.start), "membership_before_birth", f"{c.name} вступає до «{fname}» до народження"),
            (compare_points(m.start, c.death), "membership_after_death", f"{c.name} вступає до «{fname}» після смерті"),
        ]
        for outcome, rule, summary in checks:
            if outcome:
                category, severity = OUTCOME_CATEGORY[outcome]
                out.append(FindingDraft(
                    rule=rule, category=category, severity=severity, summary=summary,
                    explanation=f"Членство: {m.start.text()} — {m.end.text()}; життя: {c.birth.text()} — {c.death.text()}.",
                    evidence=[_ch(c), EvidenceDraft("membership", m.id, fname, verified=True)],
                    subject=(("character", c.id), ("membership", m.id)),
                ))
    return out


def build_dependency_graph(snap):
    graph = Graph()
    for event in snap.events:
        graph.add_node(event.id)
    for dep in snap.dependencies:
        graph.add_edge(dep.before, dep.after, dependency=dep)
    return graph


def rule_dependency_cycles(snap):
    graph = build_dependency_graph(snap)
    cycle = graph.find_cycle()
    if not cycle:
        return []
    titles = [snap.event(eid).title if snap.event(eid) else f"#{eid}" for eid in cycle]
    return [FindingDraft(
        rule="dependency_cycle", category=CONFIRMED, severity=ERROR,
        summary="Хронологічні залежності утворюють цикл",
        explanation=" → ".join(titles) + ". Така послідовність подій неможлива без часової петлі.",
        evidence=[_ev(snap.event(eid)) for eid in dict.fromkeys(cycle) if snap.event(eid)],
        subject=tuple(("event", eid) for eid in sorted(set(cycle))),
    )]


def rule_dependency_order(snap):
    """Check 'A before B' constraints, including transitive ones through undated events.

    Uses a topological order of the (acyclic) dependency graph and propagates the earliest
    admissible time of each event (longest path with min_gap weights). An event whose own
    date is earlier than this bound violates some chain of constraints; the chain is
    reported as evidence.
    """
    graph = build_dependency_graph(snap)
    try:
        order = graph.topological_sort(key=lambda n: n)
    except CycleError:
        return []  # reported by rule_dependency_cycles
    bound = {}  # event id -> (earliest admissible key, origin event id, path)
    out = []
    for eid in order:
        event = snap.event(eid)
        if event is None:
            continue
        incoming = None
        for pred in graph.predecessors(eid):
            pred_event = snap.event(pred)
            dep = graph.edge_data(pred, eid)["dependency"]
            gap = dep.min_gap or Decimal("0")
            candidates = []
            if pred_event and pred_event.start.known:
                candidates.append((pred_event.start, pred, [pred]))
            if pred in bound:
                b_point, origin, path = bound[pred]
                candidates.append((b_point, origin, path + [pred] if path[-1:] != [pred] else path))
            for point, origin, path in candidates:
                shifted = TimePoint(point.key + gap, point.precision, point.uncertainty, point.label)
                if incoming is None or shifted.key > incoming[0].key:
                    incoming = (shifted, origin, path)
        if incoming is None:
            continue
        point, origin, path = incoming
        if event.start.known:
            outcome = compare_points(point, event.start)
            if outcome:
                category, severity = OUTCOME_CATEGORY[outcome]
                chain = [snap.event(x).title for x in [*path, eid] if snap.event(x)]
                out.append(FindingDraft(
                    rule="dependency_violated", category=category, severity=severity,
                    summary=f"Порушено порядок подій: «{event.title}» має відбутися не раніше {fmt_number(point.key)}",
                    explanation="Ланцюжок залежностей: " + " → ".join(chain) + f". Дата події: {event.start.text()}.",
                    evidence=[_ev(snap.event(x)) for x in dict.fromkeys([*path, eid]) if snap.event(x)],
                    subject=(("event", origin), ("event", eid)),
                ))
            # Keep the stronger of own date and propagated bound for further propagation.
            if event.start.key >= point.key:
                continue
        bound[eid] = (point, origin, path)
    return out


def chronological_order(snap):
    """Events in a consistent temporal order: topological order of the dependency DAG,
    ties broken by known date (unknown dates go after dated predecessors)."""
    graph = build_dependency_graph(snap)
    def key(eid):
        e = snap.event(eid)
        return (e.start.key is None, e.start.key or 0, eid) if e else (True, 0, eid)
    try:
        return graph.topological_sort(key=key)
    except CycleError:
        return sorted(graph.nodes, key=key)


def _overlap(a_start, a_end, b_start, b_end):
    """True / False if periods certainly overlap / don't; None when unknown."""
    if not all(p.known for p in (a_start, b_start)):
        return None
    a_hi = a_end.key if a_end.known else None
    b_hi = b_end.key if b_end.known else None
    if a_hi is not None and a_hi < b_start.key:
        return False
    if b_hi is not None and b_hi < a_start.key:
        return False
    return True


def rule_relationship_conflicts(snap):
    """Alliance and enmity between the same pair in overlapping (or unspecified) periods."""
    out = []
    pairs = {}
    for rel in snap.relationships:
        if rel.kind in ("alliance", "enmity"):
            pairs.setdefault(frozenset([rel.source, rel.target]), []).append(rel)
    for pair, rels in pairs.items():
        allies = [r for r in rels if r.kind == "alliance"]
        enemies = [r for r in rels if r.kind == "enmity"]
        for a in allies:
            for e in enemies:
                overlap = _overlap(a.start, a.end, e.start, e.end)
                if overlap is False:
                    continue
                category, severity = (CONFIRMED, WARNING) if overlap else (POTENTIAL, INFO)
                out.append(FindingDraft(
                    rule="relationship_conflict", category=category, severity=severity,
                    summary="Одночасно союз і ворожнеча між тими самими сторонами",
                    explanation=(
                        "Періоди перетинаються." if overlap else
                        "Періоди не вказані, тому неможливо перевірити, чи це послідовні етапи стосунків."
                    ),
                    evidence=[EvidenceDraft("relationship", a.id, "союз", verified=True), EvidenceDraft("relationship", e.id, "ворожнеча", verified=True)],
                    subject=tuple(sorted(pair)) + (("relationship", a.id), ("relationship", e.id)),
                ))
    return out


def rule_relationship_lifetime(snap):
    out = []
    for rel in snap.relationships:
        for side in (rel.source, rel.target):
            if side[0] != "character":
                continue
            c = snap.character(side[1])
            if c is None:
                continue
            outcome = compare_points(rel.start, c.death)
            if outcome:
                category, severity = OUTCOME_CATEGORY[outcome]
                out.append(FindingDraft(
                    rule="relationship_after_death", category=category, severity=severity,
                    summary=f"Звʼязок із {c.name} починається після смерті персонажа",
                    explanation=f"Початок звʼязку: {rel.start.text()}; смерть: {c.death.text()}.",
                    evidence=[_ch(c), EvidenceDraft("relationship", rel.id, rel.kind, verified=True)],
                    subject=(("character", c.id), ("relationship", rel.id)),
                ))
    return out


def rule_cross_world_references(snap):
    out = []
    for rel in snap.relationships:
        worlds = {w for w in (rel.source_world, rel.target_world, rel.world_id) if w is not None}
        if len(worlds) > 1:
            out.append(FindingDraft(
                rule="cross_world_reference", category=CONFIRMED, severity=ERROR,
                summary="Звʼязок посилається на сутність з іншого світу",
                evidence=[EvidenceDraft("relationship", rel.id, rel.kind, verified=True)],
                subject=(("relationship", rel.id),),
            ))
    for event in snap.events:
        for character_id, _ in event.participants:
            c = snap.character(character_id)
            if c is None:
                out.append(FindingDraft(
                    rule="dangling_reference", category=CONFIRMED, severity=ERROR,
                    summary=f"Подія «{event.title}» посилається на неіснуючого персонажа",
                    evidence=[_ev(event)], subject=(("event", event.id), ("character", character_id)),
                ))
            elif c.world_id is not None and event.world_id is not None and c.world_id != event.world_id:
                out.append(FindingDraft(
                    rule="cross_world_reference", category=CONFIRMED, severity=ERROR,
                    summary=f"Подія «{event.title}» містить персонажа з іншого світу",
                    evidence=[_ev(event), _ch(c)], subject=(("event", event.id), ("character", c.id)),
                ))
    return out


def rule_hierarchy_cycles(snap):
    out = []
    for kind, label in (("subordination", "підпорядкування"), ("mentorship", "наставництва")):
        graph = Graph()
        for rel in snap.relationships:
            if rel.kind == kind:
                graph.add_edge(rel.source, rel.target, rel=rel)
        cycle = graph.find_cycle()
        if cycle:
            out.append(FindingDraft(
                rule="hierarchy_cycle", category=CONFIRMED, severity=WARNING,
                summary=f"Цикл у ланцюжку {label}",
                explanation=" → ".join(f"{t}#{i}" for t, i in cycle),
                evidence=[EvidenceDraft("relationship", graph.edge_data(a, b)["rel"].id, kind, verified=True) for a, b in zip(cycle, cycle[1:])],
                subject=tuple(sorted(set(cycle))),
            ))
    return out


WORLD_RULES = [
    rule_event_end_before_start,
    rule_death_before_birth,
    rule_status_conflict,
    rule_event_vs_lifetime,
    rule_membership_vs_lifetime,
    rule_dependency_cycles,
    rule_dependency_order,
    rule_relationship_conflicts,
    rule_relationship_lifetime,
    rule_cross_world_references,
    rule_hierarchy_cycles,
]


def run_world_rules(snap):
    findings = []
    for rule in WORLD_RULES:
        findings.extend(rule(snap))
    return findings
