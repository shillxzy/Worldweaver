"""Whole-book story scan: the book is read in order, piece by piece, with a story memory.

Why this shape:

* one request per piece — with Gemini usually a whole chapter — returns issues and new facts together;
* each piece gets only what concerns it: the world brief of the entities it mentions and
  remembered facts about them from earlier chapters — so contradictions across chapters
  ("lost an arm in chapter 5, claps both hands in chapter 40") become visible;
* results are saved after every chapter, and a chapter whose text, model and prompt did not
  change is not scanned again: a scan stopped by closing the laptop continues where it stopped,
  and after editing a few chapters only those are checked again (unless a full rescan is asked).
"""
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.utils import timezone

from apps.ai.backends import AIError, AIResponseError, AIUnavailable
from apps.ai.service import SCAN_PROMPT_VERSION
from apps.books.models import Chapter

from .engine.chunking import split_text
from .engine.loader import load_snapshot
from .engine.manuscript import ManuscriptAnalyzer
from .engine.rules import run_world_rules
from .engine.story import EntityIndex, Fact, recall, world_brief
from .models import AnalysisJob, ChapterScan, Finding

logger = logging.getLogger("worldweaver.analysis")
STORY_KINDS = (AnalysisJob.Kind.BOOK, AnalysisJob.Kind.BOOK_WITH_LORE, AnalysisJob.Kind.CHAPTER)


def text_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def needs_scan(scan, chapter_text, model_name, full=False):
    return (
        full or scan is None or scan.text_hash != text_hash(chapter_text) or scan.model_name != model_name
        or scan.prompt_version != SCAN_PROMPT_VERSION or scan.failed_chunks > 0
    )


def human_duration(seconds):
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} хв"
    return f"{minutes // 60} год {minutes % 60:02d} хв"


def process_story_job(job, ai_service_factory, heartbeat, persist_findings, stats):
    """Run a book (or one chapter) story scan. ``heartbeat`` raises JobCancelled on cancel."""
    started = time.perf_counter()
    book_id = job.book_id or (job.chapter.book_id if job.chapter_id else None)
    book_chapters = list(Chapter.objects.filter(book_id=book_id, book__world=job.world).order_by("order", "id").only("id", "plain_text", "title", "order"))
    targets = [c for c in book_chapters if job.kind != AnalysisJob.Kind.CHAPTER or c.id == job.chapter_id]
    if sum(len(c.plain_text) for c in targets) > settings.WW_MAX_ANALYSIS_CHARS:
        raise ValueError("too_large")

    # 1. Fast deterministic checks (rules of the world, manuscript heuristics) — saved at once.
    heartbeat(job, 0.03, "Детерміновані перевірки")
    target_qs = Chapter.objects.filter(pk__in=[c.id for c in targets])
    rules_snap = load_snapshot(job.world, target_qs)
    drafts = (run_world_rules(rules_snap) if job.kind != AnalysisJob.Kind.CHAPTER else []) + ManuscriptAnalyzer(rules_snap).run()
    persist_findings(drafts, job.world, job)

    if not job.use_ai:
        return finish(job, started, stats, ai_status="not_used")
    service = ai_service_factory()
    health = service.health()
    if not health.get("available"):
        return finish(job, started, stats, ai_status="unavailable", ai_error=health.get("error") or f"Модель «{health.get('model')}» недоступна.")
    model = service.model_name
    AnalysisJob.objects.filter(pk=job.pk).update(model_name=model)

    # 2. The whole book is the reading context (memory), even when one chapter is checked.
    snap = load_snapshot(job.world, Chapter.objects.filter(pk__in=[c.id for c in book_chapters]))
    index = EntityIndex(snap)
    order_of = {c.id: i for i, c in enumerate(book_chapters)}
    scans = {s.chapter_id: s for s in ChapterScan.objects.filter(chapter__in=book_chapters)}
    full = bool((job.params or {}).get("full"))
    todo = [c for c in targets if needs_scan(scans.get(c.id), c.plain_text, model, full)]
    todo_ids = {c.id for c in todo}
    memory = [
        Fact.from_dict(d) for cid, s in scans.items() if cid not in todo_ids for d in (s.facts or [])
    ]
    # Unchanged chapters keep their earlier AI findings; they become part of this job's results.
    Finding.objects.filter(world=job.world, chapter__in=[c for c in targets if c.id not in todo_ids], source=Finding.Source.AI).update(job=job)

    plan = [(c, split_text(c.plain_text, c.id, settings.AI_SCAN_CHUNK_CHARS, settings.AI_CHUNK_OVERLAP)) for c in todo]
    total = sum(len(chunks) for _, chunks in plan) or 1
    workers = max(1, settings.AI_SCAN_PARALLEL)
    services = [service] + [ai_service_factory() for _ in range(workers - 1)]
    done, wall, failed_total = 0, 0.0, 0
    ai_status, ai_error = "ok", ""
    for position, (chapter, chunks) in enumerate(plan, 1):
        chapter_started = time.perf_counter()
        order = order_of[chapter.id]
        eta = f" · залишилось ≈ {human_duration(wall / done * (total - done))}" if done else ""
        heartbeat(job, 0.08 + 0.88 * done / total, f"Розділ {position} з {len(plan)}: {chapter.title[:50]}{eta}")
        # Memory comes from earlier chapters only, so the pieces of one chapter can be read in parallel.
        pieces = []
        for chunk in chunks:
            keys = index.keys(chunk.text)
            pieces.append((chunk, keys, world_brief(snap, index, chunk.text, keys),
                           recall(memory, keys, before_order=order)))
        results, failed, unavailable = _scan_pieces(services, chapter, pieces, job, heartbeat)
        done += len(chunks)
        wall += time.perf_counter() - chapter_started
        if unavailable:
            ai_status, ai_error = "unavailable", unavailable
            break  # chapters finished so far are saved; the next run continues from here
        chapter_drafts, chapter_facts = [], []
        for found, facts in results:
            chapter_drafts += found
            for f in facts:
                refs = index.keys(f"{f['who']} {f['fact']} {f['quote']}")
                chapter_facts.append(Fact(f["who"], f["fact"], f["quote"], chapter.id, chapter.title, order, f["start"], refs, f["kind"]))
        # 3. Save this chapter: new AI findings replace its undecided old ones; decisions are kept.
        Finding.objects.filter(world=job.world, chapter=chapter, source=Finding.Source.AI, decision=Finding.Decision.NEW).delete()
        persist_findings(chapter_drafts, job.world, job, skip_decided=True)
        ChapterScan.objects.update_or_create(chapter=chapter, defaults={
            "text_hash": text_hash(chapter.plain_text), "model_name": model, "prompt_version": SCAN_PROMPT_VERSION,
            "facts": [f.as_dict() for f in chapter_facts], "chunks": len(chunks), "failed_chunks": failed,
            "seconds": round(time.perf_counter() - chapter_started, 1),
        })
        memory += chapter_facts
        failed_total += failed

    return finish(job, started, stats, ai_status=ai_status, ai_error=ai_error, scanned=len(plan), skipped=len(targets) - len(todo),
                  pieces=done, failed_pieces=failed_total, ai_seconds=round(wall, 1))


def _scan_with_retry(service, chunk, chapter, brief, remembered):
    """A malformed answer is retried once (small models sometimes break JSON); then the piece is skipped."""
    try:
        return service.scan_chunk(chunk.text, chapter.title, brief, remembered, chapter.id, offset=chunk.start)
    except AIResponseError:
        return service.scan_chunk(chunk.text, chapter.title, brief, remembered, chapter.id, offset=chunk.start)


def _scan_pieces(services, chapter, pieces, job, heartbeat):
    """Scan the pieces of one chapter, in parallel when there are several (model calls only — no
    database work happens in the threads). Returns (results in text order, failed count, unavailable message)."""
    results, failed, unavailable = [None] * len(pieces), 0, ""

    def scan(i):
        chunk, _keys, brief, remembered = pieces[i]
        return _scan_with_retry(services[i % len(services)], chunk, chapter, brief, remembered)

    if len(pieces) == 1 or len(services) == 1:
        outcomes = []
        for i in range(len(pieces)):
            try:
                outcomes.append((i, scan(i), None))
            except AIError as exc:
                outcomes.append((i, None, exc))
            heartbeat(job)
    else:
        pool = ThreadPoolExecutor(max_workers=len(services))
        try:
            futures = {pool.submit(scan, i): i for i in range(len(pieces))}
            outcomes = []
            for future in as_completed(futures):
                try:
                    outcomes.append((futures[future], future.result(), None))
                except AIError as exc:
                    outcomes.append((futures[future], None, exc))
                heartbeat(job)  # also the cancellation point
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
    for i, result, error in outcomes:
        if isinstance(error, AIUnavailable):
            unavailable = str(error)
        elif error is not None:
            failed += 1
            results[i] = ([], [])
        else:
            results[i] = result
    return [r for r in results if r is not None], failed, unavailable


def finish(job, started, stats, ai_status, ai_error="", **extra):
    findings = list(job.findings.all())
    job.refresh_from_db()
    job.status = AnalysisJob.Status.COMPLETED
    job.progress = 1
    job.finished_at = timezone.now()
    if ai_status == "unavailable":
        job.progress_message = "Перервано: ШІ недоступний або вичерпано ліміт. Запустіть знову — перевірка продовжиться з місця зупинки."
    elif extra.get("failed_pieces"):
        job.progress_message = f"Готово; фрагментів, які модель не змогла обробити: {extra['failed_pieces']} (їх буде перевірено наступного разу)"
    else:
        job.progress_message = "Готово" if ai_status in ("ok", "not_used") else "Готово без ШІ"
    if ai_error:
        job.error_code = "ai_unavailable" if ai_status == "unavailable" else "ai_error"
        job.error_message = ai_error[:500]
    job.stats = stats(findings, time.perf_counter() - started, ai=ai_status, **extra)
    job.save()
    return job
