import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import Profile
from apps.books.models import Book, Chapter
from apps.worlds.models import World

PASSWORD = "Sup3r-secret-pass"


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"auth": "1000/min", "user": "1000/min", "public": "1000/min"}}


def make_user(email="author@example.com", name="Авторка"):
    user = get_user_model().objects.create_user(username=email, email=email, password=PASSWORD)
    Profile.objects.create(user=user, display_name=name)
    return user


@pytest.fixture
def user(db):
    return make_user()


@pytest.fixture
def other_user(db):
    return make_user("other@example.com", "Інший")


@pytest.fixture
def client(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def other_client(other_user):
    api = APIClient()
    api.force_authenticate(other_user)
    return api


@pytest.fixture
def anon():
    return APIClient()


@pytest.fixture
def world(user):
    return World.objects.create(owner=user, name="Сяйво безодні", genre="Темне фентезі")


@pytest.fixture
def book(world):
    return Book.objects.create(world=world, title="Сяйво безодні")


def doc(*paragraphs):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs]}


@pytest.fixture
def chapter(book):
    from apps.books.documents import document_stats

    content = doc("Туман повільно сповзав із води.", "Ейра відчула, що світло кличе її додому.")
    text, words = document_stats(content)
    return Chapter.objects.create(book=book, title="Розділ 1", order=0, content=content, plain_text=text, word_count=words)
