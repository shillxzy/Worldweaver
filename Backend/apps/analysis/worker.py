"""Database-backed job queue for deep analysis.

* Jobs are claimed atomically (conditional UPDATE), so several workers never take the same job.
* A heartbeat is written while a job runs; jobs whose heartbeat is older than
  WORKER_STALE_SECONDS (e.g. the worker was killed) are re-queued or failed after
  WORKER_MAX_ATTEMPTS — this gives recovery after restarts.
* At most AI_MAX_CONCURRENT_JOBS heavy jobs run at once across all workers.
* Cancellation is cooperative: the job checks ``cancel_requested`` between fragments.
"""
import logging
import os
import socket
import traceback
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai.service import AIService

from .models import AnalysisJob
from .services import JobCancelled, process_job

logger = logging.getLogger("worldweaver.worker")
Status = AnalysisJob.Status


def worker_id():
    return f"{socket.gethostname()}:{os.getpid()}"[:80]


def recover_stale_jobs(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.WORKER_STALE_SECONDS)
    stale = AnalysisJob.objects.filter(status=Status.RUNNING, heartbeat_at__lt=cutoff)
    requeued = failed = 0
    for job in stale:
        if job.cancel_requested:
            AnalysisJob.objects.filter(pk=job.pk, status=Status.RUNNING).update(status=Status.CANCELLED, finished_at=now)
        elif job.attempts >= settings.WORKER_MAX_ATTEMPTS:
            failed += AnalysisJob.objects.filter(pk=job.pk, status=Status.RUNNING).update(
                status=Status.FAILED, error_code="worker_lost", finished_at=now,
                error_message="Обробник зупинився під час виконання завдання; ліміт спроб вичерпано.",
            )
        else:
            requeued += AnalysisJob.objects.filter(pk=job.pk, status=Status.RUNNING).update(
                status=Status.PENDING, worker_id="", progress_message="Повторна постановка в чергу після збою"
            )
    return requeued, failed


def claim_next_job(wid):
    now = timezone.now()
    fresh = now - timedelta(seconds=settings.WORKER_STALE_SECONDS)
    with transaction.atomic():
        running = AnalysisJob.objects.filter(status=Status.RUNNING, use_ai=True, heartbeat_at__gte=fresh).count()
        candidates = AnalysisJob.objects.filter(status=Status.PENDING).order_by("created_at", "id")
        if running >= settings.AI_MAX_CONCURRENT_JOBS:
            candidates = candidates.filter(use_ai=False)
        for job in candidates[:5]:
            updated = AnalysisJob.objects.filter(pk=job.pk, status=Status.PENDING).update(
                status=Status.RUNNING, worker_id=wid, started_at=now, heartbeat_at=now,
                attempts=job.attempts + 1, progress_message="Розпочато",
            )
            if updated:
                job.refresh_from_db()
                return job
    return None


def run_one(job, ai_service_factory=AIService):
    try:
        process_job(job, ai_service_factory)
        logger.info("Job %s completed", job.pk)
    except JobCancelled:
        AnalysisJob.objects.filter(pk=job.pk).update(
            status=Status.CANCELLED, finished_at=timezone.now(), progress_message="Скасовано користувачем"
        )
        logger.info("Job %s cancelled", job.pk)
    except ValueError as exc:
        code = str(exc) if str(exc) in ("too_large",) else "invalid_job"
        message = "Текст для аналізу завеликий." if code == "too_large" else "Некоректні параметри завдання."
        AnalysisJob.objects.filter(pk=job.pk).update(status=Status.FAILED, finished_at=timezone.now(), error_code=code, error_message=message)
    except Exception as exc:  # noqa: BLE001 — a crashed job must never kill the worker
        # Only the exception type is stored/logged: messages may contain manuscript text.
        # The place in our code (file, line, code) is safe to log; the exception message is not.
        where = " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.line}" for f in reversed(traceback.extract_tb(exc.__traceback__)[-4:]))
        logger.error("Job %s failed with %s at %s", job.pk, type(exc).__name__, where)
        AnalysisJob.objects.filter(pk=job.pk).update(
            status=Status.FAILED, finished_at=timezone.now(), error_code="internal_error",
            error_message=f"Внутрішня помилка аналізу ({type(exc).__name__}).",
        )
