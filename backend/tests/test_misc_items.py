"""杂事项接口测试。"""


def test_create_misc_item(client):
    resp = client.post(
        "/api/misc-items",
        json={"title": "取快递", "duration_minutes": 20, "preferred_time": "18:00"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "todo"
    assert body["duration_minutes"] == 20
    assert body["preferred_time"] == "18:00"


def test_filter_by_status(client):
    client.post("/api/misc-items", json={"title": "取快递"})
    client.post("/api/misc-items", json={"title": "剪头发", "status": "done"})

    todo = client.get("/api/misc-items", params={"status": "todo"})
    assert len(todo.json()) == 1
    assert todo.json()[0]["title"] == "取快递"

    assert len(client.get("/api/misc-items").json()) == 2


def test_update_and_delete(client):
    mid = client.post("/api/misc-items", json={"title": "取快递"}).json()["id"]

    upd = client.patch(f"/api/misc-items/{mid}", json={"status": "done"})
    assert upd.status_code == 200
    assert upd.json()["status"] == "done"

    assert client.delete(f"/api/misc-items/{mid}").status_code == 204
    assert client.get(f"/api/misc-items/{mid}").status_code == 404


def test_invalid_status_422(client):
    resp = client.post("/api/misc-items", json={"title": "x", "status": "later"})
    assert resp.status_code == 422
