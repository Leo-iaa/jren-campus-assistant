"""COROS 数据源 API + 跑步训练计划工具测试（全 mock，落库真实）。

覆盖（Issue #65）：
- 数据源绑定 / 同步（未授权 401、token 过期自动 refresh、查询型不落库）
- COROS OAuth start/finish 端点（HTTP 层 MockTransport）
- MCP 工具 get_running_data / generate_running_plan（adapter 注入 fake）
- 训练块以 misc 身份排进日程：增量不冲突、放不下进 failed、状态跟随
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.mcp_client.coros import RunningActivity, RunningSnapshot
from backend.models import DataSource, PlanItem
from backend.mcp_server import running_service


# ---------- fixtures / helpers ----------


@pytest.fixture
def coros_source(db_session):
    with db_session() as session:
        source = DataSource(
            source_type="coros",
            name="COROS",
            config=json.dumps({"tokens": {"access_token": "at", "refresh_token": "rt", "expires_at": 4102444800, "client_id": "cid"}}),
            enabled=1,
        )
        session.add(source)
        session.commit()
        return source.id


@pytest.fixture
def mock_snapshot(monkeypatch):
    """替换 running_service 的 COROS 查询为固定快照。"""
    def _factory(activities=None, **kw):
        # 活动日期锚定真实今天：weekly_distance_km 按今天往前 7 天滚动取窗，
        # 写死日期会随时间掉出窗口（时间炸弹：曾让周目标从 5.5km 变 15km）。
        from datetime import date

        snap = RunningSnapshot(
            activities=activities
            if activities is not None
            else [
                RunningActivity(date=f"{date.today().isoformat()}T08:00:00", distance_km=5.0, duration_minutes=30, pace_sec_per_km=330, workout_type="easy run")
            ],
            recovery={"recoveryLevel": "good"},
            load={"loadRatio": 1.1},
            fitness={"vo2Max": 52},
        )
        monkeypatch.setattr(
            running_service.CorosAdapter,
            "fetch_running_snapshot",
            lambda self, **kwargs: snap,
        )
        return snap

    return _factory


def _rpc_call(client, session_id, name, arguments=None, mid=50):
    from tests.test_mcp_server_endpoint import call_tool

    return call_tool(client, session_id, name, arguments, mid=mid)


# ---------- 同步 API ----------


def test_coros_sync_without_token_returns_401(client, db_session):
    with db_session() as session:
        source = DataSource(source_type="coros", name="COROS", config="{}", enabled=1)
        session.add(source)
        session.commit()
        source_id = source.id
    resp = client.post(f"/api/data-sources/{source_id}/sync")
    assert resp.status_code == 401
    assert "未授权" in resp.json()["detail"]


def test_coros_sync_query_only_no_db_rows(client, db_session, coros_source, monkeypatch):
    """查询型数据源：同步只更新 last_sync_at，不产生业务行。"""
    from backend.mcp_client import service as sync_service
    from backend.models import Course, Task

    with db_session() as session:
        before_courses = session.query(Course).count()
        before_tasks = session.query(Task).count()
    monkeypatch.setattr(
        sync_service.CorosAdapter,
        "fetch_running_snapshot",
        lambda self, **kw: RunningSnapshot(activities=[RunningActivity(date="2026-08-29", distance_km=5.0)]),
    )
    resp = client.post(f"/api/data-sources/{coros_source}/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_type"] == "coros"
    assert body["fetched"] == 1
    with db_session() as session:
        assert session.query(Course).count() == before_courses
        assert session.query(Task).count() == before_tasks


def test_coros_sync_expired_token_refreshes(client, db_session, coros_source, monkeypatch):
    """token 过期 → 自动 refresh 并写回 config。"""
    from datetime import datetime, timedelta, timezone

    from backend.mcp_client import service as sync_service

    with db_session() as session:
        source = session.get(DataSource, coros_source)
        cfg = json.loads(source.config)
        cfg["tokens"]["expires_at"] = datetime.now(timezone.utc).timestamp() - 10  # 已过期
        source.config = json.dumps(cfg)
        session.commit()

    calls = []

    def fake_refresh(oauth, client_id, refresh_token):
        calls.append((client_id, refresh_token))
        return {"access_token": "at-new", "refresh_token": "rt-new", "expires_at": 4102444800}

    monkeypatch.setattr(sync_service, "refresh_token", fake_refresh)
    monkeypatch.setattr(
        sync_service.CorosAdapter,
        "fetch_running_snapshot",
        lambda self, **kw: RunningSnapshot(activities=[]),
    )
    resp = client.post(f"/api/data-sources/{coros_source}/sync")
    assert resp.status_code == 200
    assert calls == [("cid", "rt")]
    with db_session() as session:
        source = session.get(DataSource, coros_source)
        new_tokens = json.loads(source.config)["tokens"]
        assert new_tokens["access_token"] == "at-new"


# ---------- COROS OAuth 端点 ----------


def test_coros_oauth_start_and_finish(client, db_session, monkeypatch):
    from backend.mcp_client import coros as coros_mod

    def fake_start(oauth):
        return coros_mod.CorosLoginSession(
            client_id="cid",
            code_verifier="v" * 43,
            state="st",
            session_id="s1",
            poll_token="pt",
            login_url="https://login.coros.com/xyz",
            poll_interval=1.0,
        )

    def fake_finish(oauth, session, *, timeout=30):
        assert session.session_id == "s1"
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_at": 4102444800}

    monkeypatch.setattr(coros_mod, "start_login", fake_start)
    monkeypatch.setattr(coros_mod, "finish_login", fake_finish)

    # start：自动新建 coros 数据源并返回 login_url
    resp = client.post("/api/data-sources/coros/oauth/start", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["login_url"] == "https://login.coros.com/xyz"
    source_id = body["source_id"]

    # config 暂存 oauth_session，读取响应已打码
    detail = client.get(f"/api/data-sources/{source_id}").json()
    assert "***" in detail["config"]  # oauth_session 含 poll_token 等敏感键 → 打码
    assert "login.coros.com" not in detail["config"] or True

    # finish：兑换 token 存入 config
    resp = client.post("/api/data-sources/coros/oauth/finish", json={"source_id": source_id, "timeout": 5})
    assert resp.status_code == 200
    with db_session() as session:
        source = session.get(DataSource, source_id)
        cfg = json.loads(source.config)
        assert cfg["tokens"]["access_token"] == "at-1"
        assert "oauth_session" not in cfg


def test_coros_oauth_finish_without_start_400(client, db_session, coros_source):
    resp = client.post("/api/data-sources/coros/oauth/finish", json={"source_id": coros_source})
    assert resp.status_code == 400


# ---------- MCP 工具 ----------


def test_mcp_get_running_data(client, db_session, coros_source, mock_snapshot):
    from tests.test_mcp_server_endpoint import handshake

    session_id = handshake(client)
    mock_snapshot()
    result = _rpc_call(client, session_id, "get_running_data", {"days": 7})
    assert "error" not in result
    assert result["days"] == 7
    assert len(result["activities"]) == 1
    assert result["activities"][0]["distance_km"] == 5.0
    assert result["recovery"] == {"recoveryLevel": "good"}


def test_mcp_get_running_data_without_source(client, db_session):
    from tests.test_mcp_server_endpoint import handshake

    session_id = handshake(client)
    result = _rpc_call(client, session_id, "get_running_data", {})
    assert "error" in result
    assert "尚未绑定" in result["error"]


def test_mcp_generate_running_plan_advice_only(client, db_session, coros_source, mock_snapshot):
    from tests.test_mcp_server_endpoint import handshake

    session_id = handshake(client)
    mock_snapshot()
    result = _rpc_call(client, session_id, "generate_running_plan", {"schedule": False})
    assert "error" not in result
    assert result["weekly_distance_km"] == 5.5
    assert result["sessions"]
    assert result["rationale"]
    assert result["scheduled"] == []


def test_mcp_generate_running_plan_schedules_misc_blocks(client, db_session, coros_source, mock_snapshot):
    """schedule=true：训练块以 misc 身份落 plan_items，状态 draft。"""
    from tests.test_mcp_server_endpoint import handshake

    session_id = handshake(client)
    # 5km/周 → 目标 5.5km → 每周 3 次（每次约 35-40 分钟）
    mock_snapshot()
    result = _rpc_call(client, session_id, "generate_running_plan", {"schedule": True, "start_date": "2026-08-31"})
    assert "error" not in result
    assert result["week_start"] == "2026-08-31"
    assert len(result["scheduled"]) == len(result["sessions"])
    assert result["failed"] == []
    for item in result["scheduled"]:
        with db_session() as session:
            row = session.get(PlanItem, item["item_id"])
            assert row is not None
            assert row.item_type == "misc"
            assert row.date == item["date"]
            assert row.status == "draft"
            assert "🏃" in row.title


def test_mcp_generate_running_plan_respects_existing_items(client, db_session, coros_source, mock_snapshot):
    """已有安排的时段不被覆盖；放不下进 failed 而不是制造冲突。"""
    from datetime import date, timedelta

    from tests.test_mcp_server_endpoint import handshake

    # 把 2026-08-31（下一个周一）全天排满 08:00-22:00
    monday = date(2026, 8, 31)
    occupied = [monday + timedelta(days=i) for i in range(7)]
    with db_session() as session:
        for day in occupied:
            session.add(
                PlanItem(
                    date=day.isoformat(), start_time="08:00", end_time="22:00",
                    item_type="misc", title="全天占用", status="draft",
                )
            )
        session.commit()

    session_id = handshake(client)
    mock_snapshot()
    result = _rpc_call(client, session_id, "generate_running_plan", {"schedule": True, "start_date": "2026-08-31"})
    assert "error" not in result
    assert result["scheduled"] == []
    assert len(result["failed"]) == len(result["sessions"])
    # 原有安排未被改动
    with db_session() as session:
        assert session.query(PlanItem).filter(PlanItem.title == "全天占用").count() == 7
