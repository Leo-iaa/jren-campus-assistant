"""复习计划接口测试。"""


def _make_kp(client):
    cid = client.post("/api/courses", json={"name": "高数"}).json()["id"]
    return client.post("/api/knowledge-points", json={"course_id": cid, "title": "极限"}).json()["id"]


def test_create_review(client):
    kid = _make_kp(client)
    resp = client.post(
        "/api/review-schedules",
        json={"knowledge_point_id": kid, "seq": 1, "due_date": "2026-08-18"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["seq"] == 1
    assert body["status"] == "pending"
    assert body["knowledge_point_id"] == kid


def test_create_review_missing_kp_404(client):
    resp = client.post(
        "/api/review-schedules", json={"knowledge_point_id": 999, "seq": 1, "due_date": "2026-08-18"}
    )
    assert resp.status_code == 404


def test_duplicate_seq_409(client):
    kid = _make_kp(client)
    payload = {"knowledge_point_id": kid, "seq": 1, "due_date": "2026-08-18"}
    assert client.post("/api/review-schedules", json=payload).status_code == 201
    # 同知识点同 seq → 唯一约束 → 409
    assert client.post("/api/review-schedules", json=payload).status_code == 409


def test_invalid_due_date_422(client):
    kid = _make_kp(client)
    resp = client.post(
        "/api/review-schedules", json={"knowledge_point_id": kid, "seq": 1, "due_date": "2026/08/18"}
    )
    assert resp.status_code == 422


def test_invalid_status_422(client):
    kid = _make_kp(client)
    resp = client.post(
        "/api/review-schedules",
        json={"knowledge_point_id": kid, "seq": 1, "due_date": "2026-08-18", "status": "wat"},
    )
    assert resp.status_code == 422


def test_filter_by_kp_and_status(client):
    kid = _make_kp(client)
    client.post("/api/review-schedules", json={"knowledge_point_id": kid, "seq": 1, "due_date": "2026-08-18"})
    client.post(
        "/api/review-schedules",
        json={"knowledge_point_id": kid, "seq": 2, "due_date": "2026-08-19", "status": "done"},
    )

    by_kp = client.get("/api/review-schedules", params={"knowledge_point_id": kid})
    assert len(by_kp.json()) == 2

    done = client.get("/api/review-schedules", params={"status": "done"})
    assert len(done.json()) == 1
    assert done.json()[0]["seq"] == 2


def test_update_and_delete(client):
    kid = _make_kp(client)
    rid = client.post(
        "/api/review-schedules", json={"knowledge_point_id": kid, "seq": 1, "due_date": "2026-08-18"}
    ).json()["id"]

    upd = client.patch(
        f"/api/review-schedules/{rid}",
        json={"status": "done", "completed_at": "2026-08-18T22:00:00"},
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "done"
    assert upd.json()["completed_at"] == "2026-08-18T22:00:00"

    assert client.delete(f"/api/review-schedules/{rid}").status_code == 204
    assert client.get(f"/api/review-schedules/{rid}").status_code == 404
