import pytest
from django.conf import settings

from apps.language.spell import SpellService
from apps.worlds.models import Character

pytestmark = pytest.mark.django_db

HAS_DICT = (settings.SPELL_DICT_DIR / "uk_UA.dic").exists()


def test_style_hints_are_separate_from_spelling(client):
    if not HAS_DICT:
        pytest.skip("uk_UA dictionary not installed")
    r = client.post("/api/v1/language/spellcheck/", {"text": "Вона  пішла пішла додому - швидко,так."}, format="json")
    assert r.status_code == 200
    rules = {s["rule"] for s in r.json()["style"]}
    assert {"double_space", "repeated_word", "hyphen_as_dash", "space_after_punct"} <= rules
    assert r.json()["spelling"] == []


@pytest.mark.skipif(not HAS_DICT, reason="uk_UA dictionary not installed")
def test_spelling_world_names_and_user_dictionary(client, world):
    Character.objects.create(world=world, name="Ейра Вальмонт")
    text = "Ейра Вальмонт побачила Ейру й помилкаа в тексті. Левіафанчик плив."
    data = client.post("/api/v1/language/spellcheck/", {"text": text, "world": world.id}, format="json").json()
    words = {i["word"] for i in data["spelling"]}
    assert words == {"помилкаа", "Левіафанчик"}
    issue = next(i for i in data["spelling"] if i["word"] == "помилкаа")
    assert text[issue["start"]:issue["end"]] == "помилкаа"
    assert client.post("/api/v1/language/dictionary/", {"word": "Левіафанчик"}, format="json").status_code == 201
    data = client.post("/api/v1/language/spellcheck/", {"text": text, "world": world.id}, format="json").json()
    assert {i["word"] for i in data["spelling"]} == {"помилкаа"}
    suggestions = client.get("/api/v1/language/suggest/?word=помилкаа").json()["suggestions"]
    assert "помилка" in suggestions
    assert client.get("/api/v1/language/status/").json()["available"] is True


def test_apostrophe_variants_accepted():
    if not HAS_DICT:
        pytest.skip("uk_UA dictionary not installed")
    assert SpellService.is_correct("пам’ять") and SpellService.is_correct("пам'ять") and SpellService.is_correct("памʼять")


def test_dictionary_word_validation(client):
    assert client.post("/api/v1/language/dictionary/", {"word": "<script>"}, format="json").status_code == 400


def test_spellcheck_unavailable_without_dictionary(client, settings, tmp_path, monkeypatch):
    monkeypatch.setattr(SpellService, "_dictionary", None)
    monkeypatch.setattr(SpellService, "_load_error", None)
    settings.SPELL_DICT_DIR = tmp_path
    r = client.post("/api/v1/language/spellcheck/", {"text": "текст"}, format="json")
    assert r.status_code == 503
    assert client.get("/api/v1/language/status/").json()["available"] is False
