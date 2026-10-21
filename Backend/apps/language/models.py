from django.conf import settings
from django.db import models


class DictionaryWord(models.Model):
    """A word the author told the spellchecker to accept ("ignore" / "add to dictionary")."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dictionary_words")
    word = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["word"]
        constraints = [models.UniqueConstraint(fields=["user", "word"], name="uniq_user_dictionary_word")]
