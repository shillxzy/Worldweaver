"""Analysis orchestration: deterministic checks, deep (AI) analysis jobs, persistence."""
import logging
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai.backends import AIError, AIUnavailable
from apps.books.models import Chapter
from apps.common.text import find_quote

from .engine.chunking import split_text
from .engine.loader import load_snapshot
from .engine.manuscript import ManuscriptAnalyzer
from .engine.retrieval import build_context
from .engine.rules import run_world_rules
from .engine.types import ChapterS, TimePoint, UNKNOWN
from .models import AnalysisJob, Evidence, Finding

logger = logging.getLogger("worldweaver.analysis")


class JobCancelled(Exception):
    pass


# --- persistence ------------------------------------------------------------------

def deduplicate(drafts):
    """Drop duplicates by fingerprint and overlapping AI findings on the same manuscript span."""
    result, seen = [], set()
    for draft in drafts:
        fp = draft.fingerprint()
        if fp in seen:
            continue
        if draft.source == "ai" and draft.start is not None:
            duplicate = any(
                other.source == "ai" and other.chapter_id == draft.chapter_id and other.start is not None
                and other.start < draft.end and draft.start < other.end and other.rule == draft.rule
                for other in result
            )
            if duplicate:
                continue
        seen.add(fp)
        result.append(draft)
    return result


@transaction.atomic
def persist_findings(drafts, world, job=None):
    drafts = deduplicate(drafts)
    previous = {
        f.fingerprint: (f.decision, f.decision_note)
        for f in Finding.objects.filter(world=world).exclude(decision=Finding.Decision.NEW).order_by("id")
    }
    valid_chapters = set(Chapter.objects.filter(book__world=world).values_list("id", flat=True))
    created = []
    for draft in drafts:
        fp = draft.fingerprint()
        decision, note = previous.get(fp, (Finding.Decision.NEW, ""))
        finding = Finding.objects.create(
            job=job, world=world,
            chapter_id=draft.chapter_id if draft.chapter_id in valid_chapters else None,
            rule=draft.rule[:60], fingerprint=fp, category=draft.category, severity=draft.severity,
            source=draft.source, confidence=draft.confidence, summary=draft.summary[:300],
            explanation=draft.explanation, manuscript_quote=draft.quote or "",
            position_start=draft.start, position_end=draft.end, quote_verified=draft.quote_verified,
            decision=decision, decision_note=note,
        )
        Evidence.objects.bulk_create(
            Evidence(
                finding=finding, source_type=e.source_type, source_id=e.source_id or 0,
                source_label=(e.label or "")[:200], quote=e.quote or "", position_start=e.start,
                position_end=e.end, verified=e.verified,
            )
            for e in draft.evidence
        )
        created.append(finding)
    return created


# --- deterministic analysis (synchronous, fast) -----------------------------------

def run_consistency(world, user, chapters=None):
    """World rules + manuscript heuristics. Fast and local; runs inside the request."""
    started = time.perf_counter()
    job = AnalysisJob.objects.create(
        user=user, world=world, kind=AnalysisJob.Kind.CONSISTENCY, status=AnalysisJob.Status.RUNNING,
        use_ai=False, started_at=timezone.now(),
    )
    snap = load_snapshot(world, chapters)
    drafts = run_world_rules(snap) + ManuscriptAnalyzer(snap).run()
    findings = persist_findings(drafts, world, job)
    job.status = AnalysisJob.Status.COMPLETED
    job.progress = 1
    job.finished_at = timezone.now()
    job.stats = _stats(findings, time.perf_counter() - started, chapters=len(snap.chapters), ai="not_used")
    job.save()
    return job


def _stats(findings, seconds, **extra):
    with_quotes = [f for f in findings if f.manuscript_quote]
    return {
        "findings": len(findings),
        "by_category": {c: sum(1 for f in findings if f.category == c) for c in Finding.Category.values},
        "quotes_total": len(with_quotes),
        "quotes_verified": sum(1 for f in with_quotes if f.quote_verified),
        "seconds": round(seconds, 3),
        **extra,
    }


# --- quick checks while writing (mode A) ------------------------------------------

def quick_check(chapter, text, offset=0):
    """Cheap checks on a fragment: known names, dead characters, name typos. No LLM."""
    world = chapter.book.world
    snap = load_snapshot(world, Chapter.objects.none())
    from .engine.loader import point

    fragment = ChapterS(
        id=chapter.id, title=chapter.title, order=chapter.order, text=text, book_id=chapter.book_id,
        story_time=point(chapter.story_time_key, label=chapter.story_time_label) if chapter.story_time_key is not None else TimePoint(None, UNKNOWN),
        is_flashback=chapter.is_flashback, narrator_unreliable=chapter.narrator_unreliable,
    )
    snap.chapters = [fragment]
    analyzer = ManuscriptAnalyzer(snap)
    drafts = analyzer.dead_character_active() + analyzer.ages() + analyzer.name_typos()
    mentions = [
        {"character": m.entity_id, "name": snap.character(m.entity_id).name, "start": m.start + offset, "end": m.end + offset}
        for m in analyzer.mentions(fragment)
    ]
    issues = []
    for d in drafts:
        issues.append({
            "rule": d.rule, "category": d.category, "severity": d.severity, "summary": d.summary,
            "explanation": d.explanation, "quote": d.quote,
            "start": d.start + offset if d.start is not None else None,
            "end": d.end + offset if d.end is not None else None,
        })
    return {"mentions": mentions, "issues": issues}


# --- deep analysis jobs (worker) ---------------------------------------------------

def job_chapters(job):
    if job.kind == AnalysisJob.Kind.FRAGMENT or job.kind == AnalysisJob.Kind.CHAPTER:
        return Chapter.objects.filter(pk=job.chapter_id, book__world=job.world)
    return Chapter.objects.filter(book_id=job.book_id, book__world=job.world).order_by("order", "id")


def _heartbeat(job, progress=None, message=None):
    fields = {"heartbeat_at": timezone.now()}
    if progress is not None:
        fields["progress"] = progress
    if message is not None:
        fields["progress_message"] = message[:200]
    AnalysisJob.objects.filter(pk=job.pk).update(**fields)
    if AnalysisJob.objects.filter(pk=job.pk, cancel_requested=True).exists():
        raise JobCancelled()


def process_job(job, ai_service_factory):
    """Run one deep analysis job. Called by the worker after it claimed the job."""
    started = time.perf_counter()
    chapters_qs = job_chapters(job)
    snap = load_snapshot(job.world, chapters_qs)
    total_chars = sum(len(c.text) for c in snap.chapters)
    if total_chars > settings.WW_MAX_ANALYSIS_CHARS:
        raise ValueError("too_large")

    _heartbeat(job, 0.05, "Детерміновані перевірки")
    drafts = []
    if job.kind in (AnalysisJob.Kind.BOOK, AnalysisJob.Kind.BOOK_WITH_LORE):
        drafts += run_world_rules(snap)
    fragment_offset = 0
    if job.kind == AnalysisJob.Kind.FRAGMENT and snap.chapters:
        fragment_text = (job.params or {}).get("text", "")
        chapter = snap.chapters[0]
        span = find_quote(chapter.text, fragment_text[:300]) if fragment_text else None
        fragment_offset = span[0] if span else 0
        chapter.text = fragment_text
    drafts += ManuscriptAnalyzer(snap).run()
    if fragment_offset:
        for d in drafts:
            if d.start is not None:
                d.start += fragment_offset
                d.end += fragment_offset

    ai_status = "not_used"
    ai_error = ""
    if job.use_ai:
        try:
            service = ai_service_factory()
            health = service.health()
            if not health.get("available"):
                raise AIUnavailable(
                    "Ollama не запущена." if not health.get("server") else f"Модель «{health.get('model')}» не встановлена."
                )
            AnalysisJob.objects.filter(pk=job.pk).update(model_name=service.model_name)
            drafts += _run_ai(job, snap, service, fragment_offset)
            ai_status = "ok"
        except AIUnavailable as exc:
            ai_status, ai_error = "unavailable", str(exc)
        except AIError as exc:
            ai_status, ai_error = "error", str(exc)
            logger.warning("AI step failed for job %s: %s", job.pk, exc.code)

    _heartbeat(job, 0.95, "Збереження результатів")
    findings = persist_findings(drafts, job.world, job)
    job.refresh_from_db()
    job.status = AnalysisJob.Status.COMPLETED
    job.progress = 1
    job.progress_message = "Готово" if ai_status in ("ok", "not_used") else "Готово без ШІ"
    job.finished_at = timezone.now()
    if ai_error:
        job.error_code = "ai_unavailable" if ai_status == "unavailable" else "ai_error"
        job.error_message = ai_error[:500]
    job.stats = _stats(findings, time.perf_counter() - started, chapters=len(snap.chapters), characters=total_chars, ai=ai_status)
    job.save()
    return job


def _run_ai(job, snap, service, fragment_offset=0):
    chunks = []
    for chapter in snap.chapters:
        for chunk in split_text(chapter.text, chapter.id, settings.AI_CHUNK_CHARS, settings.AI_CHUNK_OVERLAP):
            chunks.append((chapter, chunk))
    if not chunks:
        return []
    budget = settings.AI_MAX_LORE_CONTEXT_CHARS * (2 if job.kind == AnalysisJob.Kind.BOOK_WITH_LORE else 1)
    drafts = []
    for index, (chapter, chunk) in enumerate(chunks):
        _heartbeat(job, 0.1 + 0.8 * index / len(chunks), f"Фрагмент {index + 1} з {len(chunks)}: {chapter.title[:60]}")
        context = build_context(snap, chunk.text, budget_chars=budget)
        kwargs = {"chapter_id": chapter.id, "offset": chunk.start + fragment_offset}
        drafts += service.analyze_plot_holes(chunk.text, chapter.title, context, **kwargs)
        if job.kind == AnalysisJob.Kind.BOOK_WITH_LORE and context["lore"]:
            drafts += service.analyze_lore_consistency(chunk.text, chapter.title, context, **kwargs)
        if job.kind in (AnalysisJob.Kind.CHAPTER, AnalysisJob.Kind.FRAGMENT) and context["characters"]:
            drafts += service.analyze_character_consistency(chunk.text, chapter.title, context, **kwargs)
    # Re-verify manuscript quotes against the full current chapter text (positions may shift
    # between chunks because of overlap).
    texts = {c.id: c.text for c in snap.chapters}
    for draft in drafts:
        if draft.chapter_id in texts and draft.quote:
            span = find_quote(texts[draft.chapter_id], draft.quote)
            if span:
                draft.start, draft.end = span[0] + fragment_offset, span[1] + fragment_offset
    return drafts


def mark_superseded(job):
    """Older pending jobs for the same target become stale when a newer one is queued."""
    qs = AnalysisJob.objects.filter(
        user=job.user, kind=job.kind, world=job.world, book=job.book, chapter=job.chapter,
        status=AnalysisJob.Status.PENDING,
    ).exclude(pk=job.pk)
    return qs.update(status=AnalysisJob.Status.CANCELLED, progress_message="Застаріле: створено новіше завдання", finished_at=timezone.now())
