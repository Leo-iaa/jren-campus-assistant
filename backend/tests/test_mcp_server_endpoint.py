"""MCP Server 暴露层 · 端点级测试（/health 与 /mcp）。

通过真实 JSON-RPC 握手（initialize → notifications/initialized → tools/list →
tools/call）验证挂载的 Streamable HTTP 端点可用，且工具调用读写的是
conftest 注入的临时数据库（不触碰真实 jren.db）。
"""
import json
import re

from backend.models import Course, CourseSession

#: 握手用的协议版本（兼容 2024-11-05 时代的主流客户端）
PROTOCOL_VERSION = "2024-11-05"

EXPECTED_TOOLS = [
    "generate_tomorrow_plan",
    "get_today_plan_preview",
    "confirm_plan",
    "adjust_plan_item",
    "mark_done",
    "get_courses",
    "add_task",
    "get_tasks",
    "get_reviews",
]

HEADERS = {"Accept": "application/json, text/event-stream"}


def rpc(client, method: str, params: dict | None = None, mid: int = 1, session_id: str | None = None):
    """发送 JSON-RPC 请求并解析响应（兼容 SSE 与纯 JSON 两种返回形态）。"""
    headers = dict(HEADERS)
    if session_id:
        headers["mcp-session-id"] = session_id
    payload = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        payload["params"] = params
    response = client.post("/mcp", json=payload, headers=headers)
    match = re.search(r"data: (\{.*\})", response.text, re.S)
    data = json.loads(match.group(1)) if match else json.loads(response.text)
    return response, data


def handshake(client) -> str:
    """完成 MCP 握手，返回会话 id。"""
    response, data = rpc(
        client,
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
        mid=1,
    )
    assert response.status_code == 200
    assert data["result"]["protocolVersion"] == PROTOCOL_VERSION
    session_id = response.headers.get("mcp-session-id")
    assert session_id, "initialize 响应缺少 mcp-session-id"
    client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={**HEADERS, "mcp-session-id": session_id},
    )
    return session_id


def call_tool(client, session_id: str, name: str, arguments: dict | None = None, mid: int = 10):
    """调用 MCP 工具，返回解析后的 JSON；非 JSON 文本（如预览）原样返回。"""
    response, data = rpc(
        client, "tools/call", {"name": name, "arguments": arguments or {}}, mid=mid, session_id=session_id
    )
    assert response.status_code == 200, data
    text = data["result"]["content"][0]["text"]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ---------- 端点可用性 ----------


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"


def test_mcp_mounted_at_slash_mcp(client):
    paths = [getattr(route, "path", None) for route in client.app.routes]
    assert "/mcp" in paths


def test_mcp_handshake_lists_all_tools(client):
    session_id = handshake(client)
    response, data = rpc(client, "tools/list", mid=2, session_id=session_id)
    assert response.status_code == 200
    names = [tool["name"] for tool in data["result"]["tools"]]
    assert names == EXPECTED_TOOLS


def test_mcp_get_courses_returns_seeded_data(client, db_session):
    with db_session() as db:
        course = Course(name="高等数学", tier="S")
        db.add(course)
        db.commit()

    session_id = handshake(client)
    courses = call_tool(client, session_id, "get_courses")
    assert courses == [
        {"id": 1, "name": "高等数学", "code": None, "tier": "S", "color": None, "teacher": None, "notes": None}
    ]


def test_mcp_generate_plan_end_to_end(client, db_session):
    """端到端：种子数据 → 生成计划 → 预览 → 确认（无 Notion 源时静默跳过）。"""
    with db_session() as db:
        course = Course(name="高等数学", tier="S")
        db.add(course)
        db.flush()
        db.add(
            CourseSession(
                course_id=course.id, day_of_week=2, start_time="08:00", end_time="09:40", release_slot=0
            )
        )
        db.commit()

    session_id = handshake(client)
    generated = call_tool(client, session_id, "generate_tomorrow_plan", {"date": "2026-08-19"}, mid=11)
    assert generated["placed"] == 1
    assert generated["dropped"] == []

    preview = call_tool(client, session_id, "get_today_plan_preview", {"date": "2026-08-19"}, mid=12)
    assert "高等数学" in preview
    assert "待确认" in preview

    confirmed = call_tool(client, session_id, "confirm_plan", {"date": "2026-08-19"}, mid=13)
    assert confirmed["confirmed_count"] == 1
    assert confirmed["version"] == 1
    # 未绑定 Notion 数据源 → 跳过日历同步（不报错）
    assert confirmed["notion_sync"] is None


def test_mcp_tool_returns_error_text_on_bad_input(client):
    session_id = handshake(client)
    result = call_tool(client, session_id, "get_tasks", {"status": "bogus"}, mid=21)
    assert "error" in result
    assert "未知任务状态" in result["error"]


def test_mcp_add_task_end_to_end(client, db_session):
    """端到端：add_task 落库（无 Notion 源时静默跳过任务库写入），get_tasks 可查回。"""
    session_id = handshake(client)
    result = call_tool(
        client, session_id, "add_task",
        {"title": "端点测试任务", "task_type": "作业", "due_date": "2026-08-26"},
        mid=23,
    )
    assert result["task"]["title"] == "端点测试任务"
    assert result["task"]["task_type"] == "作业"
    assert result["task"]["deadline"] == "2026-08-26"
    assert result["plan_action"] in ("scheduled_today", "deferred")
    assert "已添加任务" in result["message"]
    # 未绑定 Notion 数据源 → notion_sync 为 null，不报错
    assert result["notion_sync"] is None

    tasks = call_tool(client, session_id, "get_tasks", {}, mid=24)
    assert any(t["title"] == "端点测试任务" for t in tasks)


def test_mcp_tool_missing_required_param_rejected_by_sdk(client):
    """缺必填参数时由 SDK 参数校验层拒绝（返回 isError 的文本，不进入工具）。"""
    session_id = handshake(client)
    response, data = rpc(
        client, "tools/call", {"name": "confirm_plan", "arguments": {}}, mid=22, session_id=session_id
    )
    assert response.status_code == 200
    assert data["result"]["isError"] is True
    text = data["result"]["content"][0]["text"]
    assert "validation error" in text and "date" in text
