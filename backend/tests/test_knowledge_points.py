"""知识点接口测试。"""


def _make_course(client, name="高数"):
    return client.post("/api/courses", json={"name": name}).json()["id"]


def test_create_kp_defaults(client):
    cid = _make_course(client)
    resp = client.post("/api/knowledge-points", json={"course_id": cid, "title": "极限的定义"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["difficulty"] == 3
    assert body["status"] == "active"
    assert "created_at" in body


def test_create_kp_with_difficulty_and_source(client):
    cid = _make_course(client)
    resp = client.post(
        "/api/knowledge-points",
        json={
            "course_id": cid,
            "title": "洛必达法则",
            "difficulty": 4,
            "source_path": "notes/高数/第三章.md",
            "content_snapshot": "当 0/0 或 ∞/∞ 时可用",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["difficulty"] == 4
    assert resp.json()["source_path"] == "notes/高数/第三章.md"


def test_create_kp_missing_course_404(client):
    resp = client.post("/api/knowledge-points", json={"course_id": 999, "title": "x"})
    assert resp.status_code == 404


def test_kp_difficulty_out_of_range_422(client):
    cid = _make_course(client)
    resp = client.post(
        "/api/knowledge-points", json={"course_id": cid, "title": "x", "difficulty": 6}
    )
    assert resp.status_code == 422


def test_kp_filter_by_course(client):
    c1 = _make_course(client, "高数")
    c2 = _make_course(client, "线代")
    client.post("/api/knowledge-points", json={"course_id": c1, "title": "极限"})
    client.post("/api/knowledge-points", json={"course_id": c2, "title": "矩阵"})

    resp = client.get("/api/knowledge-points", params={"course_id": c1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["title"] == "极限"

    assert len(client.get("/api/knowledge-points").json()) == 2


def test_kp_update_and_delete(client):
    cid = _make_course(client)
    kid = client.post(
        "/api/knowledge-points", json={"course_id": cid, "title": "极限", "difficulty": 2}
    ).json()["id"]

    upd = client.patch(f"/api/knowledge-points/{kid}", json={"difficulty": 5, "status": "archived"})
    assert upd.status_code == 200
    assert upd.json()["difficulty"] == 5
    assert upd.json()["status"] == "archived"

    assert client.delete(f"/api/knowledge-points/{kid}").status_code == 204
    assert client.get(f"/api/knowledge-points/{kid}").status_code == 404
