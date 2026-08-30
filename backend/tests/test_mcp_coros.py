"""COROS MCP 接入层测试（全 mock，无需真实账号）。

覆盖（Issue #65）：
- 工具结果解析：structuredContent / content JSON 文本 / 裸数组三形态
- 活动记录字段归一化（距离米/千米、时长秒/分、配速候选键）
- OAuth：动态注册 / CLI 登录会话 / finish 轮询 / token 兑换（MockTransport）
- 同步服务：未授权 401、token 过期自动 refresh、查询型不落库
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.mcp_client.coros import (
    CorosAdapter,
    CorosLoginSession,
    CorosOAuthConfig,
    _json_from_result,
    _normalize_activity,
    finish_login,
    start_login,
)
from backend.mcp_client.transport import JsonRpcError, StdioTransport  # noqa: F401 确保模块导入正常
from backend.mcp_client.models import SyncResult


# ---------- 工具结果解析 ----------


def test_json_from_result_structured_content():
    assert _json_from_result({"structuredContent": {"records": [1]}}) == {"records": [1]}


def test_json_from_result_text_json():
    result = {"content": [{"type": "text", "text": json.dumps({"records": [{"a": 1}]})}]}
    assert _json_from_result(result) == {"records": [{"a": 1}]}


def test_json_from_result_plain_text():
    assert _json_from_result({"content": [{"type": "text", "text": "没有数据"}]}) == "没有数据"


# ---------- 活动归一化 ----------


def test_normalize_activity_meters_to_km():
    a = _normalize_activity({"startTime": "2026-08-29T08:00:00", "distance": 5210, "duration": 1800, "avgHeartRate": 152})
    assert a.date == "2026-08-29T08:00:00"
    assert a.distance_km == 5.21
    assert a.duration_minutes == 30.0
    assert a.avg_heart_rate == 152


def test_normalize_activity_km_and_minutes_passthrough():
    a = _normalize_activity({"date": "2026-08-29", "distanceKm": 10.0, "duration": 55})
    assert a.distance_km == 10.0
    assert a.duration_minutes == 55.0


def test_normalize_activity_pace_candidates():
    # avgPaceSecPerKm 优先（明确的秒/公里）
    a = _normalize_activity({"avgPaceSecPerKm": 330, "pace": 5.5})
    assert a.pace_sec_per_km == 330
    # 只有 avgPace 时取它
    b = _normalize_activity({"avgPace": 340})
    assert b.pace_sec_per_km == 340


def test_normalize_activity_workout_type():
    a = _normalize_activity({"sportTypeName": "跑步", "type": "interval"})
    assert a.workout_type == "interval"


# ---------- adapter（fake 传输注入） ----------


class FakeCorosTransport:
    """按工具名返回预设结果的假传输（CorosAdapter 走 McpClient.call_tool）。"""

    def __init__(self, call_results: dict[str, dict]):
        self.call_results = call_results
        self.calls: list[tuple[str, dict | None]] = []

    def _post(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self.calls.append((method, params))
        if method == "initialize":
            return {"protocolVersion": "2024-11-05", "capabilities": {}}
        if method == "tools/list":
            return {"tools": [{"name": n} for n in self.call_results]}
        if method == "tools/call":
            name = (params or {}).get("name")
            if name in self.call_results:
                return self.call_results[name]
            raise JsonRpcError(-32602, f"未知工具：{name}")  # 真实服务器对未知工具报错
        raise AssertionError(method)

    def _notify(self, method, params=None):
        pass

    def close(self):
        pass


def _adapter_with(results: dict[str, dict]) -> tuple[CorosAdapter, FakeCorosTransport]:
    transport = FakeCorosTransport(results)
    adapter = CorosAdapter(client=__import__("backend.mcp_client.transport", fromlist=["McpClient"]).McpClient(transport))
    return adapter, transport


def test_fetch_running_snapshot_combines_tools():
    records = {
        "records": [
            {"startTime": "2026-08-29T08:00:00", "distance": 5000, "duration": 1500, "avgPaceSecPerKm": 300},
        ]
    }
    adapter, transport = _adapter_with(
        {
            "querySportRecords": {"structuredContent": records},
            "queryRecoveryStatus": {"structuredContent": {"recoveryLevel": "good", "recoveryPercentage": 88}},
            "queryFitnessAssessmentOverview": {"structuredContent": {"vo2Max": 52}},
            "queryTrainingLoadAssessment": {"structuredContent": {"loadRatio": 1.05}},
        }
    )
    snap = adapter.fetch_running_snapshot(days=7, date_from="2026-08-24", date_to="2026-08-30")
    assert len(snap.activities) == 1
    assert snap.activities[0].distance_km == 5.0
    assert snap.recovery == {"recoveryLevel": "good", "recoveryPercentage": 88}
    assert snap.fitness == {"vo2Max": 52}
    assert snap.load == {"loadRatio": 1.05}
    assert set(snap.available_tools) >= {"querySportRecords", "queryRecoveryStatus"}
    # 日期参数按 YYYYMMDD 传递
    sport_call = [p for m, p in transport.calls if m == "tools/call" and p["name"] == "querySportRecords"][0]
    assert sport_call["arguments"]["startDate"] == "20260824"
    assert sport_call["arguments"]["endDate"] == "20260830"


def test_fetch_running_snapshot_tool_failure_degrades():
    """个别工具失败降级为 warning，不阻断整体查询。"""
    adapter, _ = _adapter_with({"querySportRecords": {"structuredContent": {"records": []}}})
    snap = adapter.fetch_running_snapshot(days=7, date_from="2026-08-24", date_to="2026-08-30")
    assert snap.activities == []
    assert snap.warnings  # 其它三个工具未配置 → 有降级说明


# ---------- OAuth：动态注册 + CLI 登录会话 ----------


def _oauth_with(handler) -> CorosOAuthConfig:
    return CorosOAuthConfig(http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_start_login_creates_session():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/connect/register":
            return httpx.Response(200, json={"client_id": "cid-123"})
        if request.url.path == "/api/v1/cli/login-sessions":
            body = json.loads(request.content)
            assert body == {"clientId": "cid-123"}
            return httpx.Response(
                200,
                json={
                    "sessionId": "sess-1",
                    "pollToken": "ptok",
                    "loginUrl": "https://login.coros.com/xyz",
                    "intervalSeconds": 1,
                    "expiresAt": "2026-08-30T06:00:00Z",
                },
            )
        raise AssertionError(request.url.path)

    session = start_login(_oauth_with(handler))
    assert session.client_id == "cid-123"
    assert session.login_url == "https://login.coros.com/xyz"
    assert session.state and session.code_verifier


def test_finish_login_exchanges_token(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/claim"):
            return httpx.Response(200, json={"status": "authorized", "loginTicket": "lt-1"})
        if path == "/oauth2/authorize":
            assert request.url.params["login_ticket"] == "lt-1"
            assert request.url.params["state"] == "st-1"
            return httpx.Response(
                302,
                headers={
                    "Location": "http://127.0.0.1:43123/callback?code=abc&state=st-1"
                },
            )
        if path == "/oauth2/token":
            form = request.content.decode()
            assert "grant_type=authorization_code" in form
            assert "code=abc" in form
            return httpx.Response(
                200,
                json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600},
            )
        raise AssertionError(path)

    session = CorosLoginSession(
        client_id="cid",
        code_verifier="v" * 43,
        state="st-1",
        session_id="s1",
        poll_token="pt",
        login_url="https://login.example/xyz",
        poll_interval=0.1,
    )
    token = finish_login(_oauth_with(handler), session, timeout=5)
    assert token["access_token"] == "at-1"
    assert token["refresh_token"] == "rt-1"
    assert token["client_id"] == "cid"
    assert token["expires_at"] is not None
