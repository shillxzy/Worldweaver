from django.db import models

from apps.worlds.models import TIME_DIGITS, World, hex_color


def empty_document():
    return {"type": "doc", "content": [{"type": "paragraph"}]}


class Book(models.Model):
    class Status(models.TextChoices):
        IDEA = "idea", "Ідея"
        DRAFTING = "drafting", "Чернетка"
        REVISING = "revising", "Редагування"
        FINISHED = "finished", "Завершено"

    class Format(models.TextChoices):
        NOVEL = "novel", "Роман"
        NOVELLA = "novella", "Повість"
        SHORT_STORY = "short_story", "Оповідання"
        SCREENPLAY = "screenplay", "Сценарій"
        OTHER = "other", "Інше"

    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="books")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    genre = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFTING)
    manuscript_format = models.CharField(max_length=12, choices=Format.choices, default=Format.NOVEL)
    accent = models.CharField(max_length=7, default="#e0b36a", validators=[hex_color])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["world", "-updated_at"])]

    def __str__(self):
        return self.title


class Chapter(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Чернетка"
        REVISION = "revision", "Редагування"
        DONE = "done", "Готово"

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="chapters")
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)
    content = models.JSONField(default=empty_document)
    plain_text = models.TextField(blank=True, default="")
    word_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    revision = models.PositiveIntegerField(default=1, help_text="Зростає з кожним збереженням вмісту.")
    # Optional anchoring in the world's internal time (used by consistency checks).
    story_time_key = models.DecimalField(null=True, blank=True, **TIME_DIGITS)
    story_time_label = models.CharField(max_length=120, blank=True)
    is_flashback = models.BooleanField(default=False)
    narrator_unreliable = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["book", "order"])]

    def __str__(self):
        return self.title


class ChapterVersion(models.Model):
    class Reason(models.TextChoices):
        AUTOSAVE = "autosave", "Автозбереження"
        MANUAL = "manual", "Вручну"
        RESTORE = "restore", "Перед відновленням"
        IMPORT = "import", "Перед імпортом"

    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name="versions")
    revision = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    content = models.JSONField()
    plain_text = models.TextField(blank=True)
    word_count = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=10, choices=Reason.choices, default=Reason.AUTOSAVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["chapter", "-created_at"])]
