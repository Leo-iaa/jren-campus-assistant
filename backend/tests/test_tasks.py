"""作业任务接口测试。"""


def _make_course(client):
    return client.post("/api/courses", json={"name": "高数"}).json()["id"]


def test_create_task_with_course(client):
    cid = _make_course(client)
    resp = client.post(
        "/api/tasks",
        json={
            "course_id": cid,
            "title": "高数作业1",
            "estimated_minutes": 90,
            "deadline": "2026-08-20",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["course_id"] == cid
    assert body["source"] == "manual"
    assert body["status"] == "todo"
    assert body["estimated_minutes"] == 90


def test_create_task_without_course(client):
    resp = client.post("/api/tasks", json={"title": "买笔"})
    assert resp.status_code == 201
    assert resp.json()["course_id"] is None


def test_create_task_missing_course_404(client):
    resp = client.post("/api/tasks", json={"course_id": 999, "title": "x"})
    assert resp.status_code == 404


def test_create_notion_source(client):
    resp = client.post(
        "/api/tasks",
        json={"title": "线代作业", "source": "notion", "source_ref": "page_123"},
    )
    assert resp.status_code == 201
    assert resp.json()["source"] == "notion"
    assert resp.json()["source_ref"] == "page_123"


def test_invalid_source_422(client):
    resp = client.post("/api/tasks", json={"title": "x", "source": "wechat"})
    assert resp.status_code == 422


def test_filter_tasks(client):
    cid = _make_course(client)
    client.post("/api/tasks", json={"course_id": cid, "title": "作业A", "status": "todo"})
    client.post("/api/tasks", json={"course_id": cid, "title": "作业B", "status": "done"})

    todo = client.get("/api/tasks", params={"status": "todo"})
    assert len(todo.json()) == 1
    assert todo.json()[0]["title"] == "作业A"

    by_course = client.get("/api/tasks", params={"course_id": cid})
    assert len(by_course.json()) == 2


def test_update_and_delete(client):
    cid = _make_course(client)
    tid = client.post("/api/tasks", json={"course_id": cid, "title": "作业A"}).json()["id"]

    upd = client.patch(f"/api/tasks/{tid}", json={"status": "doing", "estimated_minutes": 60})
    assert upd.status_code == 200
    assert upd.json()["status"] == "doing"
    assert upd.json()["estimated_minutes"] == 60

    assert client.delete(f"/api/tasks/{tid}").status_code == 204
    assert client.get(f"/api/tasks/{tid}").status_code == 404
