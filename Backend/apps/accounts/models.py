from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Per-user profile and application preferences (1:1 with Django's User)."""

    THEME_CHOICES = [("dark", "Dark"), ("light", "Light")]
    LANGUAGE_CHOICES = [("uk", "Українська"), ("en", "English")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=150, blank=True)
    bio = models.TextField(blank=True, max_length=2000)
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default="dark")
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default="uk")
    quick_checks_enabled = models.BooleanField(default=True)
    spellcheck_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name or self.user.get_username()


def get_profile(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile
