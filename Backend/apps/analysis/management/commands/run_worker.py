import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.analysis.worker import claim_next_job, recover_stale_jobs, run_one, worker_id


class Command(BaseCommand):
    help = "Обробляє черговані завдання глибокого аналізу (окремий процес)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Обробити не більше одного завдання й вийти.")

    def handle(self, *args, **options):
        wid = worker_id()
        stop = {"flag": False}

        def _stop(signum, frame):
            stop["flag"] = True
            self.stdout.write("Зупинка після поточного завдання…")

        signal.signal(signal.SIGINT, _stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _stop)
        self.stdout.write(f"Worker {wid} запущено. Модель: Gemini {settings.GEMINI_MODEL}"
                          + ("" if settings.GEMINI_API_KEY else " (немає GEMINI_API_KEY у .env — аналіз ШІ недоступний)"))
        last_recovery = 0.0
        while not stop["flag"]:
            if time.monotonic() - last_recovery > 30:
                requeued, failed = recover_stale_jobs()
                if requeued or failed:
                    self.stdout.write(f"Відновлено завдань: {requeued}, позначено як невдалі: {failed}")
                last_recovery = time.monotonic()
            job = claim_next_job(wid)
            if job is None:
                if options["once"]:
                    break
                time.sleep(settings.WORKER_POLL_SECONDS)
                continue
            self.stdout.write(f"Завдання #{job.pk} ({job.kind})…")
            run_one(job)
            if options["once"]:
                break
