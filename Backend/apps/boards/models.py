from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.books.models import Book
from apps.worlds.models import World, hex_color


class Board(models.Model):
    """Idea board. Belongs either to a world or to a book (exactly one)."""

    world = models.ForeignKey(World, null=True, blank=True, on_delete=models.CASCADE, related_name="boards")
    book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.CASCADE, related_name="boards")
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(world__isnull=False) & Q(book__isnull=True)) | (Q(world__isnull=True) & Q(book__isnull=False)),
                name="board_world_xor_book",
            )
        ]

    @property
    def owner_id(self):
        return self.book.world.owner_id if self.book_id else self.world.owner_id


class BoardItem(models.Model):
    class Kind(models.TextChoices):
        COLUMN = "column", "Колонка"
        NOTE = "note", "Нотатка"
        IDEA = "idea", "Ідея"
        DRAFT = "draft", "Чернетка"
        REFERENCE = "reference", "Посилання на сутність"

    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="items")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.NOTE)
    text = models.TextField(blank=True, max_length=10000)
    color = models.CharField(max_length=7, blank=True, validators=[hex_color])
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    width = models.FloatField(default=240)
    height = models.FloatField(default=120)
    order = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [models.Index(fields=["board", "parent", "order"])]

    def clean(self):
        if self.parent_id and self.parent.board_id != self.board_id:
            raise ValidationError("Батьківський елемент належить іншій дошці.")


class BoardConnection(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="connections")
    source = models.ForeignKey(BoardItem, on_delete=models.CASCADE, related_name="outgoing")
    target = models.ForeignKey(BoardItem, on_delete=models.CASCADE, related_name="incoming")
    label = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "target"], name="uniq_board_connection"),
            models.CheckConstraint(condition=~Q(source=models.F("target")), name="board_connection_not_self"),
        ]
