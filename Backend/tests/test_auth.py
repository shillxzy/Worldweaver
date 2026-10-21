import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.worlds.models import World

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_register_login_me_logout_flow():
    api = APIClient()
    r = api.post("/api/v1/auth/register/", {"name": "Ольга", "email": "Olga@Example.com", "password": PASSWORD}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["email"] == "olga@example.com"
    assert api.get("/api/v1/auth/me/").json()["name"] == "Ольга"
    api.post("/api/v1/auth/logout/")
    assert api.get("/api/v1/auth/me/").status_code == 403
    r = api.post("/api/v1/auth/login/", {"email": "olga@example.com", "password": PASSWORD}, format="json")
    assert r.status_code == 200
    assert api.get("/api/v1/auth/me/").status_code == 200


def test_register_rejects_weak_password_and_duplicate(user):
    api = APIClient()
    r = api.post("/api/v1/auth/register/", {"name": "X", "email": "new@example.com", "password": "123"}, format="json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "validation_error"
    assert "password" in r.json()["error"]["details"]
    r = api.post("/api/v1/auth/register/", {"name": "X", "email": user.email, "password": PASSWORD}, format="json")
    assert r.status_code == 400


def test_login_wrong_password(user):
    r = APIClient().post("/api/v1/auth/login/", {"email": user.email, "password": "wrong-password"}, format="json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_csrf_enforced_for_login_and_session_writes(user):
    api = APIClient(enforce_csrf_checks=True)
    r = api.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert r.status_code == 403  # no token
    api.get("/api/v1/auth/csrf/")
    token = api.cookies["csrftoken"].value
    r = api.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json", HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 200
    token = api.cookies["csrftoken"].value  # rotated on login
    assert api.post("/api/v1/worlds/", {"name": "Без токена"}, format="json").status_code == 403
    r = api.post("/api/v1/worlds/", {"name": "З токеном"}, format="json", HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 201


def test_anonymous_cannot_access_private_resources(anon):
    for url in ["/api/v1/worlds/", "/api/v1/books/", "/api/v1/analysis/", "/api/v1/settings/", "/api/v1/boards/"]:
        assert anon.get(url).status_code == 403
        assert anon.get(url).json()["error"]["code"] == "not_authenticated"


def test_profile_and_settings_update(client, user):
    r = client.patch("/api/v1/auth/me/", {"name": "Нове імʼя", "bio": "Пишу фентезі"}, format="json")
    assert r.status_code == 200 and r.json()["bio"] == "Пишу фентезі"
    r = client.patch("/api/v1/settings/", {"theme": "light", "language": "en"}, format="json")
    assert r.json()["theme"] == "light"
    assert client.patch("/api/v1/settings/", {"theme": "neon"}, format="json").status_code == 400


def test_delete_account_requires_password_and_cascades(client, user, world):
    assert client.delete("/api/v1/auth/me/", {"password": "nope"}, format="json").status_code == 400
    assert client.delete("/api/v1/auth/me/", {"password": PASSWORD}, format="json").status_code == 204
    assert not get_user_model().objects.filter(pk=user.pk).exists()
    assert not World.objects.filter(pk=world.pk).exists()


def test_password_change(client, user):
    r = client.post("/api/v1/auth/password/", {"old_password": PASSWORD, "new_password": "Another-strong-pass1"}, format="json")
    assert r.status_code == 204
    user.refresh_from_db()
    assert user.check_password("Another-strong-pass1")
