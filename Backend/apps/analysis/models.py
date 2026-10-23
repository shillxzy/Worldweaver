from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.books.models import Book, Chapter
from apps.worlds.models import World


class AnalysisJob(models.Model):
    class Kind(models.TextChoices):
        CONSISTENCY = "consistency", "Детерміновані перевірки світу"
        FRAGMENT = "fragment", "Глибокий аналіз фрагмента"
        CHAPTER = "chapter", "Глибокий аналіз розділу"
        BOOK = "book", "Глибокий аналіз книги"
        BOOK_WITH_LORE = "book_with_lore", "Книга з урахуванням лору світу"

    class Status(models.TextChoices):
        PENDING = "pending", "Очікує"
        RUNNING = "running", "Виконується"
        COMPLETED = "completed", "Завершено"
        FAILED = "failed", "Помилка"
        CANCELLED = "cancelled", "Скасовано"

    ACTIVE = (Status.PENDING, Status.RUNNING)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="analysis_jobs")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="analysis_jobs")
    book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.CASCADE, related_name="analysis_jobs")
    chapter = models.ForeignKey(Chapter, null=True, blank=True, on_delete=models.CASCADE, related_name="analysis_jobs")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    params = models.JSONField(default=dict, blank=True)
    use_ai = models.BooleanField(default=True)
    progress = models.FloatField(default=0)
    progress_message = models.CharField(max_length=200, blank=True)
    cancel_requested = models.BooleanField(default=False)
    error_code = models.CharField(max_length=40, blank=True)
    error_message = models.CharField(max_length=500, blank=True, help_text="Ніколи не містить тексту рукопису.")
    model_name = models.CharField(max_length=120, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    worker_id = models.CharField(max_length=80, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    stats = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["user", "-created_at"]),
        ]


class Finding(models.Model):
    class Category(models.TextChoices):
        CONFIRMED = "confirmed", "Формально підтверджена невідповідність"
        POTENTIAL = "potential", "Потенційна семантична суперечність"
        INSUFFICIENT_DATA = "insufficient_data", "Недостатньо даних"
        UNVERIFIED = "unverified", "Неперевірене припущення моделі"

    class Severity(models.TextChoices):
        INFO = "info", "Інформація"
        WARNING = "warning", "Попередження"
        ERROR = "error", "Помилка"

    class Decision(models.TextChoices):
        NEW = "new", "Нове"
        ACCEPTED = "accepted", "Прийняте"
        REJECTED = "rejected", "Відхилене"
        IGNORED = "ignored", "Проігнороване"

    class Source(models.TextChoices):
        RULES = "rules", "Детерміновані правила"
        TEXT = "text", "Текстові евристики"
        AI = "ai", "Локальна модель"

    job = models.ForeignKey(AnalysisJob, null=True, blank=True, on_delete=models.CASCADE, related_name="findings")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="findings")
    chapter = models.ForeignKey(Chapter, null=True, blank=True, on_delete=models.SET_NULL, related_name="findings")
    rule = models.CharField(max_length=60, help_text="Код правила або тип проблеми, напр. 'event_before_birth'.")
    fingerprint = models.CharField(max_length=64, help_text="Стабільний хеш для дедуплікації.")
    category = models.CharField(max_length=18, choices=Category.choices)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.WARNING)
    source = models.CharField(max_length=6, choices=Source.choices, default=Source.RULES)
    confidence = models.FloatField(null=True, blank=True)
    summary = models.CharField(max_length=300)
    explanation = models.TextField(blank=True)
    manuscript_quote = models.TextField(blank=True)
    position_start = models.PositiveIntegerField(null=True, blank=True)
    position_end = models.PositiveIntegerField(null=True, blank=True)
    quote_verified = models.BooleanField(default=False)
    decision = models.CharField(max_length=8, choices=Decision.choices, default=Decision.NEW)
    decision_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["world", "decision"]), models.Index(fields=["job", "category"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(confidence__isnull=True) | (Q(confidence__gte=0) & Q(confidence__lte=1)),
                name="finding_confidence_range",
            )
        ]


class Evidence(models.Model):
    """A source cited by a finding: a chapter quote, a lore entry, an event, a character..."""

    class SourceType(models.TextChoices):
        CHAPTER = "chapter", "Розділ"
        LORE = "lore", "Запис лору"
        CHARACTER = "character", "Персонаж"
        FACTION = "faction", "Фракція"
        EVENT = "event", "Подія"
        RELATIONSHIP = "relationship", "Звʼязок"
        DEPENDENCY = "dependency", "Часова залежність"
        MEMBERSHIP = "membership", "Членство"
        PAGE = "page", "Сторінка енциклопедії"

    finding = models.ForeignKey(Finding, on_delete=models.CASCADE, related_name="evidence")
    source_type = models.CharField(max_length=12, choices=SourceType.choices)
    source_id = models.PositiveBigIntegerField()
    source_label = models.CharField(max_length=200, blank=True)
    quote = models.TextField(blank=True)
    position_start = models.PositiveIntegerField(null=True, blank=True)
    position_end = models.PositiveIntegerField(null=True, blank=True)
    verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]


class ChapterScan(models.Model):
    """The latest whole-book (story) scan of one chapter.

    ``facts`` is the chapter's contribution to the story memory: important events and state
    changes (who, what, a verified quote) that later chapters are checked against. A chapter
    whose text, model and prompt version are unchanged is not scanned again, so a long book
    scan can be stopped and resumed.
    """

    chapter = models.OneToOneField(Chapter, on_delete=models.CASCADE, related_name="scan")
    text_hash = models.CharField(max_length=64)
    model_name = models.CharField(max_length=120, blank=True)
    prompt_version = models.PositiveSmallIntegerField(default=1)
    facts = models.JSONField(default=list, blank=True)
    chunks = models.PositiveIntegerField(default=0)
    failed_chunks = models.PositiveIntegerField(default=0)
    seconds = models.FloatField(default=0)
    scanned_at = models.DateTimeField(auto_now=True)
