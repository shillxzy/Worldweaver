"""Co-writing: roles, invitations, links, comments and the public site."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.books.models import Book, Chapter
from apps.collab.models import WorldInvite, WorldMember
from apps.pages.models import Page

from .conftest import doc, make_user

pytestmark = pytest.mark.django_db


def as_user(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


@pytest.fixture
def team(world, other_user):
    """One person per role (the owner is the ``user`` fixture)."""
    people = {"outsider": make_user("out@example.com", "Сторонній")}
    for role in ("admin", "editor", "commenter", "viewer"):
        person = make_user(f"{role}@example.com", role.title())
        WorldMember.objects.create(world=world, user=person, role=role)
        people[role] = person
    return {name: as_user(u) for name, u in people.items()} | {"users": people}


def w(world, path=""):
    return f"/api/v1/worlds/{world.id}/{path}"


def test_every_role_reads_but_only_editors_change_content(team, world, book, chapter):
    chapter_url = f"/api/v1/books/{book.id}/chapters/{chapter.id}/"
    for role in ("admin", "editor", "commenter", "viewer"):
        api = team[role]
        assert api.get(w(world)).json()["my_role"] == role
        assert [b["id"] for b in api.get("/api/v1/books/").json()["results"]] == [book.id]
        assert api.get(chapter_url).json()["plain_text"]
        allowed = role in ("admin", "editor")
        r = api.patch(chapter_url, {"content": doc(f"Новий текст від {role}.")}, format="json")
        assert r.status_code == (200 if allowed else 403), (role, r.content)
        r = api.post(w(world, "characters/"), {"name": f"Персонаж {role}"}, format="json")
        assert r.status_code == (201 if allowed else 403)
        assert api.post(w(world, "pages/"), {"title": f"Сторінка {role}"}, format="json").status_code == (201 if allowed else 403)
    # outsiders see nothing at all (404, not 403: ids of foreign worlds do not leak)
    assert team["outsider"].get(chapter_url).status_code == 404
    assert team["outsider"].get(w(world)).status_code == 404
    assert team["outsider"].get("/api/v1/books/").json()["count"] == 0


def test_last_editor_is_recorded(team, world, book, chapter):
    r = team["editor"].patch(f"/api/v1/books/{book.id}/chapters/{chapter.id}/", {"content": doc("Редакторка правила.")}, format="json")
    assert r.json()["updated_by_name"] == "Editor"


def test_structural_actions_need_higher_roles(client, team, world, book):
    assert team["editor"].delete(f"/api/v1/books/{book.id}/").status_code == 403
    assert team["editor"].delete(w(world)).status_code == 403
    assert team["admin"].delete(w(world)).status_code == 403
    assert team["viewer"].get(f"/api/v1/books/{book.id}/export/").status_code == 403
    assert team["editor"].get(f"/api/v1/books/{book.id}/export/").status_code == 200
    # editors may start a new book in the shared world; viewers may not
    assert team["editor"].post("/api/v1/books/", {"title": "Друга книга", "world": world.id}, format="json").status_code == 201
    assert team["viewer"].post("/api/v1/books/", {"title": "Ні", "world": world.id}, format="json").status_code == 400
    assert team["admin"].delete(f"/api/v1/books/{book.id}/").status_code == 204


def test_member_management_rules(client, team, world):
    users = team["users"]
    members = team["viewer"].get(w(world, "members/")).json()["members"]
    assert members[0]["role"] == "owner" and len(members) == 5
    assert all("email" not in m for m in members if m["id"] != users["viewer"].pk)  # addresses only for managers
    assert all("email" in m for m in team["admin"].get(w(world, "members/")).json()["members"])

    assert team["editor"].patch(w(world, f"members/{users['viewer'].pk}/"), {"role": "editor"}, format="json").status_code == 403
    assert team["admin"].patch(w(world, f"members/{users['viewer'].pk}/"), {"role": "commenter"}, format="json").status_code == 200
    # only the owner appoints or demotes admins
    assert team["admin"].patch(w(world, f"members/{users['editor'].pk}/"), {"role": "admin"}, format="json").status_code == 403
    assert team["admin"].delete(w(world, f"members/{users['admin'].pk}/")).status_code == 204  # leaving is always allowed
    assert client.patch(w(world, f"members/{users['editor'].pk}/"), {"role": "admin"}, format="json").status_code == 200
    assert client.delete(w(world, f"members/{world.owner_id}/")).status_code == 400
    assert team["viewer"].delete(w(world, f"members/{users['editor'].pk}/")).status_code == 403
    assert team["viewer"].delete(w(world, f"members/{users['viewer'].pk}/")).status_code == 204
    assert team["viewer"].get(w(world)).status_code == 404


def test_transfer_ownership(client, team, world):
    users = team["users"]
    assert team["admin"].post(w(world, "transfer/"), {"user": users["editor"].pk}, format="json").status_code == 403
    assert client.post(w(world, "transfer/"), {"user": users["outsider"].pk}, format="json").status_code == 400
    r = client.post(w(world, "transfer/"), {"user": users["editor"].pk}, format="json")
    assert r.status_code == 200 and r.json()["my_role"] == "admin"
    world.refresh_from_db()
    assert world.owner_id == users["editor"].pk
    assert team["editor"].get(w(world)).json()["my_role"] == "owner"
    assert client.delete(w(world)).status_code == 403


def test_invite_link_with_role_expiry_and_uses(client, team, world, book, other_client, other_user):
    r = client.post(w(world, "invites/"), {"role": "admin"}, format="json")
    assert r.status_code == 400  # links never grant admin
    r = client.post(w(world, "invites/"), {"role": "editor", "max_uses": 1, "expires_in_days": 7}, format="json")
    assert r.status_code == 201
    token = r.json()["token"]
    preview = other_client.get(f"/api/v1/invites/{token}/").json()
    assert preview["world"]["name"] == world.name and preview["role"] == "editor" and preview["my_role"] is None
    r = other_client.post(f"/api/v1/invites/{token}/accept/")
    assert r.status_code == 200 and r.json() == {"world": world.id, "book": book.id, "role": "editor"}
    assert team["outsider"].post(f"/api/v1/invites/{token}/accept/").status_code == 400  # used up

    expired = WorldInvite.objects.create(world=world, role="viewer", expires_at=timezone.now() - timedelta(minutes=1))
    assert team["outsider"].post(f"/api/v1/invites/{expired.token}/accept/").status_code == 400

    link = client.post(w(world, "invites/"), {"role": "viewer"}, format="json").json()
    assert client.delete(w(world, f"invites/{link['id']}/")).status_code == 204
    assert team["outsider"].post(f"/api/v1/invites/{link['token']}/accept/").status_code == 400
    # managing invitations needs admin rights
    assert team["editor"].get(w(world, "invites/")).status_code == 403


def test_accepting_never_downgrades(client, team, world):
    link = client.post(w(world, "invites/"), {"role": "viewer"}, format="json").json()
    team["editor"].post(f"/api/v1/invites/{link['token']}/accept/")
    assert WorldMember.objects.get(world=world, user=team["users"]["editor"]).role == "editor"


def test_personal_invite_by_email(client, world, other_client, team):
    assert client.post(w(world, "invites/"), {"email": "editor@example.com"}, format="json").status_code == 400  # already in
    r = client.post(w(world, "invites/"), {"email": "Other@Example.com", "role": "commenter"}, format="json")
    assert r.status_code == 201 and r.json()["kind"] == "email"
    token = r.json()["token"]
    assert team["outsider"].post(f"/api/v1/invites/{token}/accept/").status_code == 403  # another address
    mine = other_client.get("/api/v1/invites/mine/").json()
    assert [i["world"]["id"] for i in mine] == [world.id]
    assert other_client.post(f"/api/v1/invites/{token}/accept/").json()["role"] == "commenter"
    assert other_client.get("/api/v1/invites/mine/").json() == []


def test_decline_personal_invite(client, world, other_client):
    token = client.post(w(world, "invites/"), {"email": "other@example.com"}, format="json").json()["token"]
    assert other_client.post(f"/api/v1/invites/{token}/decline/").status_code == 204
    assert other_client.get("/api/v1/invites/mine/").json() == []
    assert other_client.post(f"/api/v1/invites/{token}/accept/").status_code == 400


def test_comments_permissions(client, team, world, chapter):
    url = w(world, "comments/")
    assert team["viewer"].get(url, {"chapter": chapter.id}).status_code == 403
    r = team["commenter"].post(url, {"chapter": chapter.id, "body": "Тут збилась хронологія", "quote": "Туман"}, format="json")
    assert r.status_code == 201
    cid = r.json()["id"]
    reply = team["editor"].post(url, {"parent": cid, "body": "Виправлю"}, format="json").json()
    assert reply["chapter"] == chapter.id and reply["parent"] == cid
    assert team["editor"].patch(f"{url}{cid}/", {"body": "чуже"}, format="json").status_code == 403
    r = team["editor"].patch(f"{url}{cid}/", {"resolved": True}, format="json")
    assert r.status_code == 200 and r.json()["resolved"] and r.json()["resolved_by_name"] == "Editor"
    counts = client.get(w(world, "comment-counts/"), {"book": chapter.book_id}).json()
    assert counts["chapters"] == {}
    assert team["commenter"].delete(f"{url}{reply['id']}/").status_code == 403
    assert team["admin"].delete(f"{url}{reply['id']}/").status_code == 204
    chapter.refresh_from_db()
    assert "Туман" in chapter.plain_text  # comments never touch the text
    assert team["commenter"].post(url, {"body": "без цілі"}, format="json").status_code == 400


def test_public_site_shows_only_what_the_owner_marked(client, team, world, book, chapter, anon):
    hidden = Chapter.objects.create(book=book, title="Чернетка", order=1, content=doc("секрет"), plain_text="секрет")
    villain = Page.objects.create(world=world, title="Таємний лиходій")
    hero = Page.objects.create(world=world, title="Ейра", content={
        "type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "ворог", "marks": [{"type": "link", "attrs": {"href": f"page:{villain.id}"}}]},
        ]}],
    })
    assert team["admin"].get(w(world, "public/")).status_code == 403  # owner only
    assert anon.get("/api/v1/public/anything/").status_code == 404

    r = client.patch(w(world, "public/"), {
        "enabled": True, "books": {str(book.id): True}, "chapters": {str(chapter.id): True}, "pages": {str(hero.id): True},
    }, format="json")
    token = r.json()["token"]
    site = anon.get(f"/api/v1/public/{token}/").json()
    assert [b["title"] for b in site["books"]] == [book.title]
    assert [c["id"] for c in site["books"][0]["chapters"]] == [chapter.id]
    assert [p["title"] for p in site["pages"]] == ["Ейра"]
    assert anon.get(f"/api/v1/public/{token}/chapters/{hidden.id}/").status_code == 404
    assert anon.get(f"/api/v1/public/{token}/pages/{villain.id}/").status_code == 404
    page = anon.get(f"/api/v1/public/{token}/pages/{hero.id}/").json()
    assert page["content"]["content"][0]["content"][0] == {"type": "text", "text": "ворог"}  # link to a hidden page removed
    assert "Туман" in str(anon.get(f"/api/v1/public/{token}/chapters/{chapter.id}/").json()["content"])

    # a new link replaces the old one; switching off hides everything
    new_token = client.patch(w(world, "public/"), {"regenerate": True}, format="json").json()["token"]
    assert new_token != token and anon.get(f"/api/v1/public/{token}/").status_code == 404
    client.patch(w(world, "public/"), {"enabled": False}, format="json")
    assert anon.get(f"/api/v1/public/{new_token}/").status_code == 404


def test_public_flags_cannot_touch_other_worlds(client, other_client, other_user, world):
    from apps.worlds.models import World

    foreign = World.objects.create(owner=other_user, name="Чужий")
    foreign_book = Book.objects.create(world=foreign, title="Чужа книга")
    client.patch(w(world, "public/"), {"books": {str(foreign_book.id): True}}, format="json")
    foreign_book.refresh_from_db()
    assert foreign_book.is_public is False


def test_shared_world_in_search_and_analysis(team, world, chapter):
    assert team["viewer"].get("/api/v1/search/", {"q": "Туман"}).json()["results"]
    assert team["viewer"].post(w(world, "consistency/"), {}, format="json").status_code == 403
    assert team["editor"].post(w(world, "consistency/"), {}, format="json").status_code == 201
