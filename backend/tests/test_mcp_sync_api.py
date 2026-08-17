"""数据源同步 / 启停 / OAuth API 测试。

adapter 层全 mock（monkeypatch service 内的 adapter 类），落库走真实临时数据库，
iCal 同步用合成 .ics 样例（tests/fakes.SAMPLE_ICS）。
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

from backend.mcp_client.models import CourseSessionItem, NoteItem, TaskItem
from backend.mcp_client.oauth import OAuthToken
from tests.fakes import SAMPLE_ICS


def _create_source(client, source_type="ical", config=None, name=None):
    resp = client.post(
        "/api/data-sources",
        json={
            "source_type": source_type,
            "name": name or source_type,
            "config": json.dumps(config or {}, ensure_ascii=False),
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _courses(client):
    return client.get("/api/courses").json()


def _sessions(client, course_id):
    return client.get(f"/api/courses/{course_id}/sessions").json()


# ---------- iCal 同步 ----------


def test_ical_sync_creates_courses_and_sessions(client, tmp_path):
    ics_file = tmp_path / "schedule.ics"
    ics_file.write_text(SAMPLE_ICS, encoding="utf-8")
    source = _create_source(client, "ical", {"ics_path": str(ics_file)})

    resp = client.post(f"/api/data-sources/{source['id']}/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_type"] == "ical"
    assert body["fetched"] == 2  # 高数（合并）+ 大学英语；DAILY/无 RRULE 被跳过
    assert body["created"] == 4  # 2 门课程 + 2 个时间块
    assert len(body["warnings"]) == 2

    courses = _courses(client)
    assert {c["name"] for c in courses} == {"高等数学", "大学英语"}
    math = next(c for c in courses if c["name"] == "高等数学")
    assert math["teacher"] == "李四"  # 多 VEVENT 合并后取最新教师
    sessions = _sessions(client, math["id"])
    assert len(sessions) == 1
    assert sessions[0]["day_of_week"] == 0
    assert sessions[0]["start_time"] == "08:00"
    assert sessions[0]["location"] == "教西A1-201"

    # 最近同步时间已记录
    updated = client.get(f"/api/data-sources/{source['id']}").json()
    assert updated["last_sync_at"]


def test_ical_sync_idempotent(client, tmp_path):
    ics_file = tmp_path / "schedule.ics"
    ics_file.write_text(SAMPLE_ICS, encoding="utf-8")
    source = _create_source(client, "ical", {"ics_path": str(ics_file)})

    first = client.post(f"/api/data-sources/{source['id']}/sync").json()
    second = client.post(f"/api/data-sources/{source['id']}/sync").json()
    assert first["created"] == 4
    assert second["created"] == 0
    assert second["skipped"] == 2  # 已有且无变化
    assert len(_courses(client)) == 2


def test_ical_sync_merge_keeps_manual_edits(client, tmp_path):
    """merge 模式：手改的教室/时间不被覆盖（手动维护兜底）。"""
    ics_file = tmp_path / "schedule.ics"
    ics_file.write_text(SAMPLE_ICS, encoding="utf-8")
    source = _create_source(client, "ical", {"ics_path": str(ics_file)})
    client.post(f"/api/data-sources/{source['id']}/sync")

    math = next(c for c in _courses(client) if c["name"] == "高等数学")
    sid = _sessions(client, math["id"])[0]["id"]
    client.patch(f"/api/course-sessions/{sid}", json={"location": "改到-101"})

    merged = client.post(f"/api/data-sources/{source['id']}/sync", json={"mode": "merge"}).json()
    assert _sessions(client, math["id"])[0]["location"] == "改到-101"  # 手改保留
    assert merged["updated"] == 0

    # overwrite 模式 → iCal 字段全量覆盖
    overwritten = client.post(f"/api/data-sources/{source['id']}/sync", json={"mode": "overwrite"}).json()
    assert _sessions(client, math["id"])[0]["location"] == "教西A1-201"
    assert overwritten["updated"] >= 1


def test_ical_sync_with_ics_content(client):
    """不配置 ics_path，直接在请求体提交 .ics 文本。"""
    source = _create_source(client, "ical", {})
    resp = client.post(f"/api/data-sources/{source['id']}/sync", json={"ics_content": SAMPLE_ICS})
    assert resp.status_code == 200
    assert resp.json()["fetched"] == 2


def test_ical_sync_without_source_400(client):
    source = _create_source(client, "ical", {})
    resp = client.post(f"/api/data-sources/{source['id']}/sync")
    assert resp.status_code == 400


def test_sync_disabled_source_409(client):
    source = _create_source(client, "ical", {"ics_path": "C:/x.ics"})
    client.post(f"/api/data-sources/{source['id']}/disable")
    resp = client.post(f"/api/data-sources/{source['id']}/sync")
    assert resp.status_code == 409


# ---------- 启停 ----------


def test_enable_disable_endpoints(client):
    source = _create_source(client, "obsidian", {"vault_path": "C:/vault"})
    assert source["enabled"] is True

    disabled = client.post(f"/api/data-sources/{source['id']}/disable").json()
    assert disabled["enabled"] is False

    enabled = client.post(f"/api/data-sources/{source['id']}/enable").json()
    assert enabled["enabled"] is True


# ---------- Notion 同步 ----------


def test_notion_sync_creates_and_updates_tasks(client, monkeypatch):
    source = _create_source(
        client, "notion", {"database_id": "db1", "tokens": {"access_token": "at"}}
    )
    fetched = [
        TaskItem(title="高数作业1", source_ref="page1", deadline="2026-08-20", course_name="高等数学", status="doing"),
        TaskItem(title="英语作文", source_ref="page2", deadline="2026-08-25"),
    ]
    fake = MagicMock()
    fake.fetch_tasks.return_value = fetched
    monkeypatch.setattr("backend.mcp_client.service.NotionAdapter", lambda config, access_token: fake)

    resp = client.post(f"/api/data-sources/{source['id']}/sync")
    assert resp.status_code == 200
    assert resp.json()["fetched"] == 2
    assert resp.json()["created"] == 2

    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 2
    t1 = next(t for t in tasks if t["source_ref"] == "page1")
    assert t1["source"] == "notion"
    assert t1["deadline"] == "2026-08-20"
    assert t1["status"] == "doing"

    # 再次同步 → 幂等更新，不新建
    fake.fetch_tasks.return_value = [
        TaskItem(title="高数作业1（改）", source_ref="page1", deadline="2026-08-21", status="done"),
    ]
    again = client.post(f"/api/data-sources/{source['id']}/sync").json()
    assert again["created"] == 0
    assert again["updated"] == 1
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 2
    updated_task = next(t for t in tasks if t["source_ref"] == "page1")
    assert updated_task["title"] == "高数作业1（改）"
    assert updated_task["status"] == "done"


def test_notion_sync_requires_auth(client):
    source = _create_source(client, "notion", {})
    resp = client.post(f"/api/data-sources/{source['id']}/sync")
    assert resp.status_code == 401


def test_notion_sync_refreshes_expired_token(client, monkeypatch):
    expired = {"access_token": "old", "refresh_token": "rt", "expires_at": time.time() - 100}
    source = _create_source(client, "notion", {"database_id": "db1", "tokens": expired})

    captured: dict = {}

    def fake_oauth_builder(config, http=None):
        fake = MagicMock()
        fake.refresh.return_value = OAuthToken(
            access_token="new-token", refresh_token="rt", expires_at=time.time() + 3600
        )
        return fake

    monkeypatch.setattr("backend.mcp_client.service.build_oauth_client", fake_oauth_builder)

    fake = MagicMock()
    fake.fetch_tasks.return_value = [TaskItem(title="任务", source_ref="p1")]
    monkeypatch.setattr(
        "backend.mcp_client.service.NotionAdapter",
        lambda config, access_token: captured.update(token=access_token) or fake,
    )

    resp = client.post(f"/api/data-sources/{source['id']}/sync")
    assert resp.status_code == 200
    assert captured["token"] == "new-token"  # 用的是刷新后的 token

    cfg = json.loads(client.get(f"/api/data-sources/{source['id']}").json()["config"])
    assert cfg["tokens"]["access_token"] == "new-token"  # 新 token 已写回 config


def test_notion_sync_missing_database_id_400(client, monkeypatch):
    source = _create_source(client, "notion", {"tokens": {"access_token": "at"}})
    fake = MagicMock()
    fake.fetch_tasks.side_effect = ValueError("缺少 database_id")
    monkeypatch.setattr("backend.mcp_client.service.NotionAdapter", lambda config, access_token: fake)
    resp = client.post(f"/api/data-sources/{source['id']}/sync")
    assert resp.status_code == 400


# ---------- Obsidian 同步 ----------


def test_obsidian_sync_queries_and_records_time(client, monkeypatch):
    source = _create_source(client, "obsidian", {"vault_path": "C:/vault"})
    fake = MagicMock()
    fake.search.return_value = [NoteItem(path="数学/高数.md", title="高数", excerpt="极限的定义")]
    monkeypatch.setattr("backend.mcp_client.service.ObsidianAdapter", lambda config: fake)

    resp = client.post(f"/api/data-sources/{source['id']}/sync", json={"query": "极限"})
    assert resp.status_code == 200
    assert resp.json()["fetched"] == 1
    assert resp.json()["created"] == 0  # 只查询不落库
    assert fake.search.called

    updated = client.get(f"/api/data-sources/{source['id']}").json()
    assert updated["last_sync_at"]
    assert len(_courses(client)) == 0  # 没有产生任何课程


# ---------- Notion OAuth ----------


def test_oauth_start_generates_url_and_persists_state(client):
    resp = client.post(
        "/api/data-sources/notion/oauth/start",
        json={"client_id": "cid-1", "redirect_uri": "http://localhost:5173/oauth/notion/callback"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "code_challenge=" in body["authorization_url"]
    assert "client_id=cid-1" in body["authorization_url"]

    source = client.get(f"/api/data-sources/{body['source_id']}").json()
    assert source["source_type"] == "notion"
    config = json.loads(source["config"])
    assert config["client_id"] == "cid-1"
    assert config["oauth_state"]
    assert config["oauth_code_verifier"]


def test_oauth_start_with_existing_source(client):
    source = _create_source(client, "notion", {"client_id": "cid-2"})
    resp = client.post(
        "/api/data-sources/notion/oauth/start",
        json={"source_id": source["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["source_id"] == source["id"]


def test_oauth_start_with_env_client_id(client, monkeypatch):
    monkeypatch.setenv("JREN_NOTION_CLIENT_ID", "env-cid")
    resp = client.post("/api/data-sources/notion/oauth/start")
    assert resp.status_code == 200
    assert "client_id=env-cid" in resp.json()["authorization_url"]


def test_oauth_start_without_client_id_400(client):
    resp = client.post("/api/data-sources/notion/oauth/start")
    assert resp.status_code == 400
    assert client.get("/api/data-sources").json() == []  # 失败不留脏数据


def test_oauth_callback_exchanges_and_stores_token(client, monkeypatch):
    start = client.post(
        "/api/data-sources/notion/oauth/start", json={"client_id": "cid"}
    ).json()
    sid = start["source_id"]
    state = json.loads(client.get(f"/api/data-sources/{sid}").json()["config"])["oauth_state"]

    fake_oauth = MagicMock()
    fake_oauth.exchange_code.return_value = OAuthToken(
        access_token="at-final", refresh_token="rt-final", expires_at=1234567890.0
    )
    monkeypatch.setattr("backend.api.data_sources.build_oauth_client", lambda config: fake_oauth)

    resp = client.post(
        "/api/data-sources/notion/oauth/callback",
        json={"source_id": sid, "code": "code-1", "state": state},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    config = json.loads(client.get(f"/api/data-sources/{sid}").json()["config"])
    assert config["tokens"]["access_token"] == "at-final"
    assert "oauth_state" not in config  # 一次性 state 已清除
    assert "oauth_code_verifier" not in config


def test_oauth_callback_wrong_state_400(client):
    start = client.post(
        "/api/data-sources/notion/oauth/start", json={"client_id": "cid"}
    ).json()
    resp = client.post(
        "/api/data-sources/notion/oauth/callback",
        json={"source_id": start["source_id"], "code": "x", "state": "wrong"},
    )
    assert resp.status_code == 400
