import io

import pytest
from PIL import Image

from apps.worlds.models import GraphLayout

pytestmark = pytest.mark.django_db


def image(size=(300, 400), fmt="PNG", name="cover.png"):
    buffer = io.BytesIO()
    Image.new("RGB", size, "purple").save(buffer, format=fmt)
    buffer.seek(0)
    buffer.name = name
    return buffer


def test_book_cover_upload_read_delete_and_isolation(client, other_client, book):
    url = f"/api/v1/books/{book.id}/cover/"
    assert client.get(url).status_code == 404
    bad = io.BytesIO(b"not an image")
    bad.name = "x.png"
    assert client.post(url, {"cover": bad}, format="multipart").status_code == 400
    r = client.post(url, {"cover": image((2400, 3200))}, format="multipart")
    assert r.status_code == 200 and r.json()["has_cover"] is True
    r = client.get(url)
    assert r.status_code == 200 and r["Content-Type"] == "image/png"
    with Image.open(io.BytesIO(r.content)) as img:
        assert max(img.size) <= 1600  # downscaled on upload
    assert other_client.get(url).status_code == 404
    assert other_client.post(url, {"cover": image()}, format="multipart").status_code == 404
    assert client.get("/api/v1/books/").json()["results"][0]["has_cover"] is True
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_avatar_upload_and_delete(client, anon):
    url = "/api/v1/auth/me/avatar/"
    assert client.get(url).status_code == 404
    r = client.post(url, {"avatar": image((512, 512), "JPEG", "a.jpg")}, format="multipart")
    assert r.status_code == 200 and r.json()["has_avatar"] is True
    assert client.get("/api/v1/auth/me/").json()["has_avatar"] is True
    assert client.get(url)["Content-Type"] == "image/jpeg"
    assert anon.get(url).status_code == 403
    assert client.delete(url).json()["has_avatar"] is False


def test_graph_layout_roundtrip_and_validation(client, other_client, world):
    url = f"/api/v1/worlds/{world.id}/graph-layout/relations/"
    assert client.get(url).json()["positions"] == {}
    r = client.put(url, {"positions": {"character:1": [10.25, -20], "faction:2": [0, 0]}}, format="json")
    assert r.status_code == 200 and r.json()["positions"]["character:1"] == [10.2, -20.0]
    assert client.get(url).json()["positions"]["faction:2"] == [0.0, 0.0]
    assert GraphLayout.objects.get(world=world, view="relations")
    for bad in [{"lore:1": [0, 0]}, {"character:1": [0]}, {"character:1": ["a", 1]}, {"character:1": [1e9, 0]}, ["x"]]:
        assert client.put(url, {"positions": bad}, format="json").status_code == 400
    assert client.get(f"/api/v1/worlds/{world.id}/graph-layout/unknown/").status_code == 404
    assert other_client.get(url).status_code == 404
