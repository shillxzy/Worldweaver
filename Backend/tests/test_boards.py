import pytest

pytestmark = pytest.mark.django_db


def test_board_lifecycle_and_layout_persistence(client, other_client, book):
    r = client.post("/api/v1/boards/", {"title": "Щоденник", "book": book.id, "with_default_columns": True}, format="json")
    assert r.status_code == 201, r.content
    board = r.json()
    columns = [i for i in board["items"] if i["kind"] == "column"]
    assert len(columns) == 3
    base = f"/api/v1/boards/{board['id']}"
    note = client.post(f"{base}/items/", {"kind": "note", "text": "Ейра зраджує орден", "parent": columns[0]["id"]}, format="json").json()
    other = client.post(f"{base}/items/", {"kind": "idea", "text": "Перлина — підробка", "parent": columns[0]["id"], "order": 1}, format="json").json()
    r = client.post(f"{base}/connections/", {"source": note["id"], "target": other["id"], "label": "наслідок"}, format="json")
    assert r.status_code == 201
    assert client.post(f"{base}/connections/", {"source": note["id"], "target": note["id"]}, format="json").status_code == 400
    r = client.post(f"{base}/layout/", {"items": [{"id": note["id"], "parent": columns[2]["id"], "order": 0, "x": 10.5, "y": 20}]}, format="json")
    assert r.status_code == 200
    reloaded = client.get(f"/api/v1/boards/?book={book.id}").json()["results"][0]
    moved = next(i for i in reloaded["items"] if i["id"] == note["id"])
    assert (moved["parent"], moved["x"], moved["y"]) == (columns[2]["id"], 10.5, 20)
    assert len(reloaded["connections"]) == 1
    assert other_client.get(f"/api/v1/boards/{board['id']}/").status_code == 404
    assert other_client.post(f"{base}/items/", {"text": "x"}, format="json").status_code == 404


def test_board_validation(client, book, world):
    assert client.post("/api/v1/boards/", {"title": "X"}, format="json").status_code == 400
    assert client.post("/api/v1/boards/", {"title": "X", "book": book.id, "world": world.id}, format="json").status_code == 400
    board = client.post("/api/v1/boards/", {"title": "Світ", "world": world.id}, format="json").json()
    base = f"/api/v1/boards/{board['id']}"
    assert client.post(f"{base}/items/", {"text": "x", "width": 1}, format="json").status_code == 400
    assert client.post(f"{base}/items/", {"text": "x", "metadata": ["not", "dict"]}, format="json").status_code == 400
    other_board = client.post("/api/v1/boards/", {"title": "Інша", "world": world.id}, format="json").json()
    foreign_item = client.post(f"/api/v1/boards/{other_board['id']}/items/", {"text": "y"}, format="json").json()
    assert client.post(f"{base}/items/", {"text": "x", "parent": foreign_item["id"]}, format="json").status_code == 400
    r = client.post(f"{base}/layout/", {"items": [{"id": foreign_item["id"], "x": 1}]}, format="json")
    assert r.status_code == 400
