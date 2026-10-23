import os

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_no_missing_migrations():
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)


@pytest.mark.django_db
def test_openapi_schema_generates(client):
    r = client.get("/api/v1/schema/")
    assert r.status_code == 200
    body = r.content.decode()
    assert "/api/v1/worlds/{world_pk}/characters/" in body and "/api/v1/analysis/{id}/cancel/" in body


@pytest.mark.django_db
def test_unknown_url_returns_json_404(client):
    r = client.get("/api/v1/does-not-exist/")
    assert r.status_code == 404


def test_production_settings_refuse_missing_secret(monkeypatch):
    import importlib

    import config.settings as s

    monkeypatch.setenv("DJANGO_DEBUG", "false")
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured):
        importlib.reload(s)
    monkeypatch.setenv("DJANGO_DEBUG", os.environ.get("DJANGO_DEBUG_ORIG", "true"))
    importlib.reload(s)


@pytest.mark.django_db
def test_seed_demo_is_idempotent_and_scoped(user, other_user):
    from apps.books.models import Book, Chapter

    call_command("seed_demo", email=user.email, verbosity=0)
    call_command("seed_demo", email=user.email, verbosity=0)
    assert Book.objects.filter(world__owner=user).count() == 2
    assert Book.objects.filter(world__owner=other_user).count() == 0
    assert Chapter.objects.filter(book__world__owner=user).exclude(plain_text="").count() == 4


@pytest.mark.gemini
@pytest.mark.skipif(os.environ.get("RUN_GEMINI_TESTS") != "1", reason="set RUN_GEMINI_TESTS=1 with GEMINI_API_KEY in .env (sends test text to Google)")
def test_real_gemini_roundtrip():
    from apps.ai.service import AIService
    from apps.analysis.engine.types import CharacterS, TimePoint
    from decimal import Decimal

    service = AIService()
    assert service.health()["available"], "GEMINI_API_KEY is missing or not accepted"
    kael = CharacterS(1, "Каель", status="dead", death=TimePoint(Decimal(340)))
    findings = service.analyze_plot_holes("— Ходімо, — сказав Каель.", "Тест", {"characters": [kael]}, chapter_id=1)
    assert isinstance(findings, list)
