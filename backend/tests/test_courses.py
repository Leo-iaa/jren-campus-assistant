"""课程 CRUD 接口测试。"""


def test_create_course_default_tier(client):
    resp = client.post("/api/courses", json={"name": "高数"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] > 0
    assert data["tier"] == "A"
    assert "created_at" in data


def test_create_course_with_fields(client):
    resp = client.post(
        "/api/courses",
        json={"name": "考研数学", "tier": "S", "teacher": "王老师", "color": "#ff0000", "notes": "重点"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["tier"] == "S"
    assert data["teacher"] == "王老师"
    assert data["color"] == "#ff0000"


def test_create_course_invalid_tier_422(client):
    resp = client.post("/api/courses", json={"name": "x", "tier": "D"})
    assert resp.status_code == 422


def test_create_course_empty_name_422(client):
    resp = client.post("/api/courses", json={"name": ""})
    assert resp.status_code == 422


def test_list_courses_and_filter_by_tier(client):
    client.post("/api/courses", json={"name": "高数", "tier": "A"})
    client.post("/api/courses", json={"name": "考研数学", "tier": "S"})
    client.post("/api/courses", json={"name": "水课", "tier": "B"})

    all_resp = client.get("/api/courses")
    assert all_resp.status_code == 200
    assert len(all_resp.json()) == 3

    s_resp = client.get("/api/courses", params={"tier": "S"})
    assert len(s_resp.json()) == 1
    assert s_resp.json()[0]["name"] == "考研数学"


def test_get_course(client):
    cid = client.post("/api/courses", json={"name": "高数"}).json()["id"]
    resp = client.get(f"/api/courses/{cid}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "高数"


def test_get_course_404(client):
    resp = client.get("/api/courses/999")
    assert resp.status_code == 404


def test_patch_course_partial_update(client):
    cid = client.post("/api/courses", json={"name": "高数"}).json()["id"]
    resp = client.patch(f"/api/courses/{cid}", json={"tier": "B", "teacher": "李老师"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "B"
    assert data["teacher"] == "李老师"
    assert data["name"] == "高数"  # 未传字段保持不变


def test_patch_course_invalid_tier_422(client):
    cid = client.post("/api/courses", json={"name": "高数"}).json()["id"]
    resp = client.patch(f"/api/courses/{cid}", json={"tier": "X"})
    assert resp.status_code == 422


def test_delete_course(client):
    cid = client.post("/api/courses", json={"name": "高数"}).json()["id"]
    assert client.delete(f"/api/courses/{cid}").status_code == 204
    assert client.get(f"/api/courses/{cid}").status_code == 404
