"""课程时间块接口测试。"""


def _make_course(client, name="高数"):
    return client.post("/api/courses", json={"name": name}).json()["id"]


def test_create_and_list_sessions(client):
    cid = _make_course(client)
    resp = client.post(
        f"/api/courses/{cid}/sessions",
        json={"day_of_week": 0, "start_time": "08:00", "end_time": "09:40", "location": "教1-101"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["course_id"] == cid
    assert body["release_slot"] == 0
    assert body["location"] == "教1-101"

    listed = client.get(f"/api/courses/{cid}/sessions")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_create_session_missing_course_404(client):
    resp = client.post(
        "/api/courses/999/sessions",
        json={"day_of_week": 0, "start_time": "08:00", "end_time": "09:40"},
    )
    assert resp.status_code == 404


def test_duplicate_session_409(client):
    cid = _make_course(client)
    payload = {"day_of_week": 0, "start_time": "08:00", "end_time": "09:40"}
    assert client.post(f"/api/courses/{cid}/sessions", json=payload).status_code == 201
    # 同课程同天同时段 → 数据库唯一约束 → 409
    assert client.post(f"/api/courses/{cid}/sessions", json=payload).status_code == 409


def test_session_time_format_422(client):
    cid = _make_course(client)
    resp = client.post(
        f"/api/courses/{cid}/sessions",
        json={"day_of_week": 0, "start_time": "8:00", "end_time": "09:40"},
    )
    assert resp.status_code == 422


def test_session_end_before_start_422(client):
    """结束时间不晚于开始时间 → 422（此前会被接受入库，导致规划器崩溃）。"""
    cid = _make_course(client)
    resp = client.post(
        f"/api/courses/{cid}/sessions",
        json={"day_of_week": 0, "start_time": "10:00", "end_time": "09:00"},
    )
    assert resp.status_code == 422
    # 等值也非法
    resp2 = client.post(
        f"/api/courses/{cid}/sessions",
        json={"day_of_week": 0, "start_time": "10:00", "end_time": "10:00"},
    )
    assert resp2.status_code == 422
    # 更新路径同样校验
    sid = client.post(
        f"/api/courses/{cid}/sessions",
        json={"day_of_week": 0, "start_time": "10:00", "end_time": "11:00"},
    ).json()["id"]
    assert client.patch(f"/api/course-sessions/{sid}", json={"end_time": "09:30"}).status_code == 422


def test_session_day_of_week_out_of_range_422(client):
    cid = _make_course(client)
    resp = client.post(
        f"/api/courses/{cid}/sessions",
        json={"day_of_week": 7, "start_time": "08:00", "end_time": "09:40"},
    )
    assert resp.status_code == 422


def test_session_flat_crud(client):
    cid = _make_course(client)
    sid = client.post(
        f"/api/courses/{cid}/sessions",
        json={"day_of_week": 1, "start_time": "10:00", "end_time": "11:40"},
    ).json()["id"]

    assert client.get(f"/api/course-sessions/{sid}").status_code == 200

    upd = client.patch(f"/api/course-sessions/{sid}", json={"release_slot": 1, "location": "机房"})
    assert upd.status_code == 200
    assert upd.json()["release_slot"] == 1
    assert upd.json()["location"] == "机房"

    assert client.delete(f"/api/course-sessions/{sid}").status_code == 204
    assert client.get(f"/api/course-sessions/{sid}").status_code == 404
