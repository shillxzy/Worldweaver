import io

import pytest
from PIL import Image

from apps.worlds.models import Character, Faction, TimelineEvent, World

pytestmark = pytest.mark.django_db


def base(world):
    return f"/api/v1/worlds/{world.id}"


def test_world_crud_and_search(client):
    r = client.post("/api/v1/worlds/", {"name": "Катарсис", "genre": "Фантастика", "rules": "Памʼять можна стерти."}, format="json")
    assert r.status_code == 201
    wid = r.json()["id"]
    client.post("/api/v1/worlds/", {"name": "Інший світ"}, format="json")
    r = client.get("/api/v1/worlds/?search=Катар")
    assert [w["id"] for w in r.json()["results"]] == [wid]
    assert client.patch(f"/api/v1/worlds/{wid}/", {"tech_level": "майбутнє"}, format="json").json()["tech_level"] == "майбутнє"
    assert client.delete(f"/api/v1/worlds/{wid}/").status_code == 204


def test_data_isolation_between_users(client, other_client, world, chapter):
    c = Character.objects.create(world=world, name="Каель")
    for url in [f"/api/v1/worlds/{world.id}/", f"{base(world)}/characters/", f"{base(world)}/characters/{c.id}/",
                f"/api/v1/books/{chapter.book_id}/", f"/api/v1/books/{chapter.book_id}/chapters/{chapter.id}/"]:
        assert other_client.get(url).status_code == 404, url
    assert other_client.get("/api/v1/worlds/").json()["count"] == 0
    assert other_client.patch(f"{base(world)}/characters/{c.id}/", {"name": "Хак"}, format="json").status_code == 404
    assert other_client.delete(f"/api/v1/worlds/{world.id}/").status_code == 404
    # Creating a book inside a foreign world is rejected by validation.
    r = other_client.post("/api/v1/books/", {"title": "X", "world": world.id}, format="json")
    assert r.status_code == 400
    assert client.get(f"{base(world)}/characters/{c.id}/").status_code == 200


def test_invalid_ids_do_not_crash(client, world):
    assert client.get("/api/v1/worlds/99999999999999999999999/").status_code == 404
    assert client.get(f"{base(world)}/characters/abc/").status_code == 404
    r = client.post(f"{base(world)}/lore/", {"title": "X", "related_characters": [10**30]}, format="json")
    assert r.status_code == 400
    r = client.post(f"{base(world)}/timeline/", {"title": "X", "participants": [{"character": "zzz"}]}, format="json")
    assert r.status_code == 400


def test_lore_crud_tags_and_search(client, world):
    r = client.post(f"{base(world)}/lore/", {"title": "Перлина Сяйва", "content": "Джерело світла з безодні.", "category": "item", "tags": ["Світло", "артефакт"]}, format="json")
    assert r.status_code == 201, r.content
    assert sorted(r.json()["tags"]) == ["артефакт", "світло"]
    lid = r.json()["id"]
    assert client.get(f"{base(world)}/lore/?search=безодні").json()["count"] == 1
    assert client.get(f"{base(world)}/lore/?tag=світло").json()["count"] == 1
    assert client.get(f"{base(world)}/lore/?category=magic").json()["count"] == 0
    assert client.post(f"{base(world)}/lore/", {"title": "Y", "category": "custom"}, format="json").status_code == 400
    assert client.patch(f"{base(world)}/lore/{lid}/", {"tags": []}, format="json").json()["tags"] == []


def test_character_crud_validation_and_filters(client, world):
    payload = {"name": "Ейра Вальмонт", "aliases": ["Ейра", "ейра", "Картографка"], "birth_key": "320", "death_key": "300",
               "facts": [{"label": "Очі", "value": "сірі"}]}
    r = client.post(f"{base(world)}/characters/", payload, format="json")
    assert r.status_code == 400 and "death_key" in r.json()["error"]["details"]
    payload["death_key"] = None
    r = client.post(f"{base(world)}/characters/", payload, format="json")
    assert r.status_code == 201
    assert r.json()["aliases"] == ["Ейра", "Картографка"]
    assert client.get(f"{base(world)}/characters/?search=Картограф").json()["count"] == 1
    assert client.get(f"{base(world)}/characters/?status=dead").json()["count"] == 0


def _png(size=(64, 64)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "teal").save(buffer, format="PNG")
    buffer.seek(0)
    buffer.name = "../../evil name.png"
    return buffer


def test_portrait_upload_validation_and_private_access(client, other_client, world):
    c = Character.objects.create(world=world, name="Каель")
    url = f"{base(world)}/characters/{c.id}/portrait/"
    fake = io.BytesIO(b"<?php echo 1; ?>")
    fake.name = "x.png"
    assert client.post(url, {"portrait": fake}, format="multipart").status_code == 400
    r = client.post(url, {"portrait": _png()}, format="multipart")
    assert r.status_code == 200 and r.json()["has_portrait"]
    c.refresh_from_db()
    assert ".." not in c.portrait.name and "evil" not in c.portrait.name
    r = client.get(url)
    assert r.status_code == 200 and r["Content-Type"] == "image/png"
    assert r.content[1:4] == b"PNG"
    assert other_client.get(url).status_code == 404
    assert client.delete(url).status_code == 204


def test_portrait_size_limit(client, world, settings):
    settings.WW_MAX_PORTRAIT_BYTES = 100
    c = Character.objects.create(world=world, name="Каель")
    r = client.post(f"{base(world)}/characters/{c.id}/portrait/", {"portrait": _png((300, 300))}, format="multipart")
    assert r.status_code == 400


def test_factions_and_memberships(client, world):
    f = client.post(f"{base(world)}/factions/", {"name": "Ордо Глибин", "color": "#3fb8c9"}, format="json").json()
    assert client.post(f"{base(world)}/factions/", {"name": "X", "color": "red"}, format="json").status_code == 400
    c = Character.objects.create(world=world, name="Ейра")
    r = client.post(f"{base(world)}/memberships/", {"character": c.id, "faction": f["id"], "start_key": "330", "end_key": "320"}, format="json")
    assert r.status_code == 400
    r = client.post(f"{base(world)}/memberships/", {"character": c.id, "faction": f["id"], "role": "архіваріус", "start_key": "330"}, format="json")
    assert r.status_code == 201
    assert client.get(f"{base(world)}/factions/").json()["results"][0]["members_count"] == 1
    assert client.get(f"{base(world)}/characters/{c.id}/").json()["memberships"][0]["faction_name"] == "Ордо Глибин"
    assert client.get(f"{base(world)}/characters/?faction={f['id']}").json()["count"] == 1


def test_cross_world_references_rejected(client, user, world):
    other_world = World.objects.create(owner=user, name="Другий світ")
    foreign = Character.objects.create(world=other_world, name="Чужинець")
    f = Faction.objects.create(world=world, name="Ордо")
    r = client.post(f"{base(world)}/memberships/", {"character": foreign.id, "faction": f.id}, format="json")
    assert r.status_code == 400
    r = client.post(f"{base(world)}/relationships/", {"kind": "alliance", "source": {"type": "character", "id": foreign.id}, "target": {"type": "faction", "id": f.id}}, format="json")
    assert r.status_code == 400
    r = client.post(f"{base(world)}/timeline/", {"title": "X", "participants": [{"character": foreign.id}]}, format="json")
    assert r.status_code == 400


def test_relationships_validation_and_cycles(client, world):
    a = Character.objects.create(world=world, name="А")
    b = Character.objects.create(world=world, name="Б")
    f = Faction.objects.create(world=world, name="Ф")
    ref = lambda t, i: {"type": t, "id": i}  # noqa: E731
    r = client.post(f"{base(world)}/relationships/", {"kind": "subordination", "source": ref("character", a.id), "target": ref("character", b.id)}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["source"] == {"type": "character", "id": a.id, "label": "А"}
    r = client.post(f"{base(world)}/relationships/", {"kind": "subordination", "source": ref("character", b.id), "target": ref("character", a.id)}, format="json")
    assert r.status_code == 400  # cycle in hierarchy
    r = client.post(f"{base(world)}/relationships/", {"kind": "family", "source": ref("character", b.id), "target": ref("character", a.id)}, format="json")
    assert r.status_code == 201  # family relations may be reciprocal
    r = client.post(f"{base(world)}/relationships/", {"kind": "enmity", "source": ref("character", a.id), "target": ref("character", a.id)}, format="json")
    assert r.status_code == 400
    r = client.post(f"{base(world)}/relationships/", {"kind": "membership", "source": ref("character", a.id), "target": ref("faction", f.id), "start_key": "10", "end_key": "5"}, format="json")
    assert r.status_code == 400
    assert client.get(f"{base(world)}/relationships/?entity_type=character&entity_id={a.id}").json()["count"] == 2
    a.delete()
    assert client.get(f"{base(world)}/relationships/").json()["count"] == 0  # cascade


def test_timeline_events_order_participants_and_dependencies(client, world, chapter):
    c = Character.objects.create(world=world, name="Каель")
    mk = lambda **kw: client.post(f"{base(world)}/timeline/", kw, format="json")  # noqa: E731
    e3 = mk(title="Без дати").json()
    e2 = mk(title="Друга", start_key="212", start_label="212 рік").json()
    e1 = mk(title="Перша", start_key="1", participants=[{"character": c.id, "role": "participant"}], chapters=[chapter.id]).json()
    assert e1["participants"][0]["character_name"] == "Каель"
    titles = [e["title"] for e in client.get(f"{base(world)}/timeline/").json()["results"]]
    assert titles == ["Перша", "Друга", "Без дати"]
    assert mk(title="X", start_key="10", end_key="5").status_code == 400
    assert mk(title="X", start_key="10", uncertainty="-1").status_code == 400
    r = client.post(f"{base(world)}/dependencies/", {"before": e1["id"], "after": e2["id"]}, format="json")
    assert r.status_code == 201
    client.post(f"{base(world)}/dependencies/", {"before": e2["id"], "after": e3["id"]}, format="json")
    r = client.post(f"{base(world)}/dependencies/", {"before": e3["id"], "after": e1["id"]}, format="json")
    assert r.status_code == 400 and "цикл" in r.json()["error"]["message"]
    assert client.post(f"{base(world)}/dependencies/", {"before": e1["id"], "after": e1["id"]}, format="json").status_code == 400
    r = client.get(f"{base(world)}/chronology/").json()
    assert r["order"] == [e1["id"], e2["id"], e3["id"]] and not r["has_cycle"]
    assert TimelineEvent.objects.get(pk=e1["id"]).chapters.count() == 1


def test_world_search(client, world, chapter):
    Character.objects.create(world=world, name="Ейра Вальмонт", summary="Картографка")
    r = client.get(f"{base(world)}/search/?q=ейра").json()
    types = {item["type"] for item in r["results"]}
    assert {"character", "chapter"} <= types
    assert client.get("/api/v1/search/?q=Сяйво").json()["results"][0]["type"] == "book"
