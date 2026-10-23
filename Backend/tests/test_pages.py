import pytest

from apps.pages.models import Page, PageLink
from apps.worlds.models import Character, Faction, LoreEntry

from .conftest import doc

pytestmark = pytest.mark.django_db


def url(world, rest=""):
    return f"/api/v1/worlds/{world.id}/pages/{rest}"


def link_doc(text, page_id):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "Див. "},
        {"type": "text", "text": text, "marks": [{"type": "link", "attrs": {"href": f"page:{page_id}", "target": "_blank"}}]},
    ]}]}


def test_blank_page_create_edit_reload(client, world):
    r = client.post(url(world), {"title": "Ціна безсмертя"}, format="json")
    assert r.status_code == 201, r.content
    page = r.json()
    assert page["page_type"] == "note" and page["properties"] == [] and page["entity_type"] is None
    content = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Суть"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "Кожне воскресіння забирає спогад."}]},
    ]}
    r = client.patch(url(world, f"{page['id']}/"), {"title": "Ціна безсмертя (правило)", "content": content, "base_revision": 1}, format="json")
    assert r.status_code == 200 and r.json()["revision"] == 2
    again = client.get(url(world, f"{page['id']}/")).json()
    assert again["title"] == "Ціна безсмертя (правило)" and "забирає спогад" in again["plain_text"]
    r = client.patch(url(world, f"{page['id']}/"), {"content": doc("старе"), "base_revision": 1}, format="json")
    assert r.status_code == 409


def test_templates_create_linked_records_and_free_properties(client, world):
    templates = client.get(f"/api/v1/page-templates/?world={world.id}").json()
    assert {"blank", "character", "faction", "location"} <= {t["key"] for t in templates}
    r = client.post(url(world), {"title": "Каель", "template": "character"}, format="json")
    page = r.json()
    assert page["page_type"] == "character" and page["entity_type"] == "character"
    assert [p["label"] for p in page["properties"]][:2] == ["Короткий опис", "Вік"]
    assert "Біографія" in page["plain_text"]
    character = Character.objects.get(pk=page["entity_id"])
    assert character.name == "Каель"
    # rename page -> record follows; aliases sync too
    client.patch(url(world, f"{page['id']}/"), {"title": "Каель Ворн", "aliases": ["Ворон"]}, format="json")
    character.refresh_from_db()
    assert character.name == "Каель Ворн" and character.aliases == ["Ворон"]
    # properties: rename, retype, delete, add custom, reorder — nothing is mandatory
    props = page["properties"]
    p_url = url(world, f"{page['id']}/properties/")
    assert client.patch(f"{p_url}{props[0]['id']}/", {"label": "Суть", "value": "Капітан варти"}, format="json").status_code == 200
    assert client.patch(f"{p_url}{props[1]['id']}/", {"kind": "number", "value": 34}, format="json").json()["value"] == 34
    assert client.patch(f"{p_url}{props[1]['id']}/", {"value": "багато"}, format="json").status_code == 400
    assert client.delete(f"{p_url}{props[2]['id']}/").status_code == 204
    custom = client.post(p_url, {"label": "Улюблена пісня", "kind": "text", "value": "Пісня моря"}, format="json").json()
    ids = [p["id"] for p in client.get(url(world, f"{page['id']}/")).json()["properties"]]
    assert custom["id"] in ids
    r = client.post(f"{p_url}reorder/", {"order": list(reversed(ids))}, format="json")
    assert [p["id"] for p in r.json()] == list(reversed(ids))
    # faction and lore-type templates
    f = client.post(url(world), {"title": "Орден попелу", "template": "faction"}, format="json").json()
    assert Faction.objects.get(pk=f["entity_id"]).name == "Орден попелу"
    loc = client.post(url(world), {"title": "Північна столиця", "template": "location"}, format="json").json()
    entry = LoreEntry.objects.get(pk=loc["entity_id"])
    assert entry.category == "location"
    client.patch(url(world, f"{loc['id']}/"), {"content": doc("Місто з чорного каменю.")}, format="json")
    entry.refresh_from_db()
    assert entry.content == "Місто з чорного каменю."


def test_tree_move_and_delete_rules(client, world):
    root = client.post(url(world), {"title": "Імперія"}, format="json").json()
    child = client.post(url(world), {"title": "Історія", "parent": root["id"]}, format="json").json()
    grand = client.post(url(world), {"title": "Війни", "parent": child["id"]}, format="json").json()
    detail = client.get(url(world, f"{grand['id']}/")).json()
    assert [c["title"] for c in detail["breadcrumbs"]] == ["Імперія", "Історія"]
    assert client.get(url(world, f"{root['id']}/")).json()["children"][0]["has_children"] is True
    assert client.get(url(world, "?parent=root")).json()["count"] == 1
    # cannot move into own descendant
    assert client.post(url(world, f"{root['id']}/move/"), {"parent": grand["id"]}, format="json").status_code == 400
    other = client.post(url(world), {"title": "Магія"}, format="json").json()
    r = client.post(url(world, f"{grand['id']}/move/"), {"parent": other["id"]}, format="json")
    assert r.status_code == 200 and r.json()["parent"] == other["id"]
    r = client.post(url(world, f"{other['id']}/move/"), {"parent": None, "position": 0}, format="json")
    assert [p["title"] for p in client.get(url(world, "?parent=root&ordering=sort_order")).json()["results"]] == ["Магія", "Імперія"]
    # deleting a page with children needs an explicit choice
    assert client.delete(url(world, f"{root['id']}/")).status_code == 400
    assert client.delete(url(world, f"{root['id']}/?children=lift")).json()["deleted"] == 1
    assert Page.objects.get(pk=child["id"]).parent_id is None
    assert client.delete(url(world, f"{other['id']}/?children=delete")).json()["deleted"] == 2


def test_internal_links_backlinks_and_broken_links(client, world, user):
    from apps.worlds.models import World

    a = client.post(url(world), {"title": "Каель"}, format="json").json()
    b = client.post(url(world), {"title": "Північна столиця"}, format="json").json()
    r = client.patch(url(world, f"{a['id']}/"), {"content": link_doc("столиці", b["id"])}, format="json")
    assert r.status_code == 200
    mark = r.json()["content"]["content"][0]["content"][1]["marks"][0]
    assert mark == {"type": "link", "attrs": {"href": f"page:{b['id']}"}}  # target attr dropped
    backlinks = client.get(url(world, f"{b['id']}/")).json()["backlinks"]
    assert backlinks == [{"id": a["id"], "title": "Каель", "icon": "", "page_type": "note", "origins": ["content"]}]
    # property links count as well
    prop = client.post(url(world, f"{b['id']}/properties/"), {"label": "Правитель", "kind": "page", "value": a["id"]}, format="json")
    assert prop.status_code == 201
    assert client.get(url(world, f"{a['id']}/")).json()["backlinks"][0]["origins"] == ["property"]
    # cross-world references are rejected for properties and stored as broken for text
    foreign = Page.objects.create(world=World.objects.create(owner=user, name="Інший"), title="Чужа")
    assert client.post(url(world, f"{b['id']}/properties/"), {"label": "X", "kind": "page", "value": foreign.id}, format="json").status_code == 400
    r = client.patch(url(world, f"{a['id']}/"), {"content": link_doc("чужа", foreign.id)}, format="json")
    assert r.json()["links"] == [{"target_ref": foreign.id, "origin": "content", "broken": True, "title": None}]
    # deleting the target turns a link into a broken one
    client.patch(url(world, f"{a['id']}/"), {"content": link_doc("столиці", b["id"])}, format="json")
    Page.objects.filter(pk=b["id"]).delete()
    assert PageLink.objects.get(source_id=a["id"]).target_id is None
    assert client.get(url(world, f"{a['id']}/")).json()["links"][0]["broken"] is True


@pytest.mark.parametrize("href", ["javascript:alert(1)", "page:abc", "data:text/html,x", "ftp://x"])
def test_unsafe_links_rejected(client, world, href):
    page = client.post(url(world), {"title": "X"}, format="json").json()
    bad = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [{"type": "link", "attrs": {"href": href}}]}]}]}
    assert client.patch(url(world, f"{page['id']}/"), {"content": bad}, format="json").status_code == 400


def test_pages_isolation_lookup_and_by_entity(client, other_client, world):
    page = client.post(url(world), {"title": "Ордо Глибин", "template": "faction"}, format="json").json()
    client.patch(url(world, f"{page['id']}/"), {"aliases": ["Орден Глибин"]}, format="json")
    assert other_client.get(url(world, f"{page['id']}/")).status_code == 404
    assert other_client.post(url(world), {"title": "x"}, format="json").status_code == 404
    assert [p["id"] for p in client.get(url(world, "lookup/?q=орден")).json()] == [page["id"]]
    # records created through the structured API (e.g. graph quick-create) get a page automatically
    c = client.post(f"/api/v1/worlds/{world.id}/characters/", {"name": "Міра"}, format="json").json()
    assert c["page_id"] is not None
    r = client.get(url(world, f"by-entity/?type=character&id={c['id']}")).json()
    assert r["id"] == c["page_id"] and r["title"] == "Міра"


def test_lookup_finds_inflected_names(client, world):
    jon = client.post(url(world), {"title": "Джонатан Андерсон", "template": "character"}, format="json").json()
    wtf = client.post(url(world), {"title": "World Trade Federation", "template": "faction"}, format="json").json()
    client.patch(url(world, f"{wtf['id']}/"), {"aliases": ["Федерація"]}, format="json")
    client.post(url(world), {"title": "Брюс Адамс", "template": "character"}, format="json")
    ids = lambda q: [p["id"] for p in client.get(url(world, "lookup/"), {"q": q}).json()]
    assert ids("Джонатаном Андерсоном") == [jon["id"]]
    assert ids("джонатана") == [jon["id"]]
    assert ids("Федерацією") == [wtf["id"]]
    assert ids("Максимом") == []


def test_save_as_template_and_create_from_it(client, world):
    page = client.post(url(world), {"title": "Божество", "page_type": "deity"}, format="json").json()
    client.post(url(world, f"{page['id']}/properties/"), {"label": "Домен", "kind": "tags", "value": ["море"]}, format="json")
    tpl = client.post(url(world, f"{page['id']}/save-as-template/"), {"name": "Божество"}, format="json").json()
    new = client.post(url(world), {"title": "Левіафан", "user_template": tpl["id"]}, format="json").json()
    assert new["page_type"] == "deity" and [p["label"] for p in new["properties"]] == ["Домен"]
    assert new["properties"][0]["value"] is None  # structure copied, values not
    assert client.delete(f"/api/v1/page-templates/{tpl['id']}/").status_code == 204


def test_relevant_pages_for_chapter(client, world, book, chapter):
    client.post(url(world), {"title": "Ейра", "template": "character"}, format="json")
    client.post(url(world), {"title": "Безодня"}, format="json")
    r = client.get(f"/api/v1/books/{book.id}/chapters/{chapter.id}/relevant-pages/").json()
    assert [p["title"] for p in r["pages"]] == ["Ейра"]


def test_world_and_account_deletion_with_nested_pages(client, world):
    from .conftest import PASSWORD

    root = client.post(url(world), {"title": "Імперія"}, format="json").json()
    client.post(url(world), {"title": "Історія", "parent": root["id"]}, format="json")
    assert client.delete(f"/api/v1/worlds/{world.id}/").status_code == 204
    assert not Page.objects.exists()
    world2 = client.post("/api/v1/worlds/", {"name": "Другий"}, format="json").json()
    parent = client.post(f"/api/v1/worlds/{world2['id']}/pages/", {"title": "A"}, format="json").json()
    client.post(f"/api/v1/worlds/{world2['id']}/pages/", {"title": "B", "parent": parent["id"]}, format="json")
    assert client.delete("/api/v1/auth/me/", {"password": PASSWORD}, format="json").status_code == 204
    assert not Page.objects.exists()
