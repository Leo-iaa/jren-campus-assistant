"""MCP 传输层测试：stdio（假子进程）+ streamable HTTP（httpx.MockTransport）。"""
from __future__ import annotations

import json
import sys

import httpx
import pytest

from backend.mcp_client.transport import (
    HttpTransport,
    JsonRpcError,
    McpClient,
    StdioTransport,
    extract_result_items,
)

# 假 MCP 服务器：逐行读取 stdin 的 JSON-RPC，按方法/工具名返回固定结果
FAKE_SERVER = r'''
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue  # 通知
    method = msg.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake-mcp", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "echo tool"}]}
    elif method == "tools/call" and msg.get("params", {}).get("name") == "echo":
        result = {"content": [{"type": "text", "text": "pong"}]}
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found"}}) + "\n")
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\n")
    sys.stdout.flush()
'''


def _write_fake_server(tmp_path):
    script = tmp_path / "fake_server.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return script


# ---------- stdio ----------


def test_stdio_roundtrip(tmp_path):
    script = _write_fake_server(tmp_path)
    client = McpClient(StdioTransport([sys.executable, str(script)]))
    try:
        info = client.initialize()
        assert info["serverInfo"]["name"] == "fake-mcp"
        assert client.list_tools()[0]["name"] == "echo"
        result = client.call_tool("echo", {"x": 1})
        assert result["content"][0]["text"] == "pong"
    finally:
        client.close()


def test_stdio_jsonrpc_error(tmp_path):
    script = _write_fake_server(tmp_path)
    client = McpClient(StdioTransport([sys.executable, str(script)]))
    try:
        with pytest.raises(JsonRpcError) as exc:
            client.call_tool("不存在的工具")
        assert exc.value.code == -32601
    finally:
        client.close()


# ---------- streamable HTTP ----------


def test_http_json_response_with_session_and_auth():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        headers = {}
        if "Mcp-Session-Id" not in request.headers:
            headers["Mcp-Session-Id"] = "sess-1"
        if "id" not in body:
            return httpx.Response(202, headers=headers)  # 通知 → 202
        result = {"serverInfo": {"name": "http-fake", "version": "1"}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}, headers=headers)

    transport = HttpTransport(
        "https://mcp.example.com/mcp",
        access_token="tok-123",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client = McpClient(transport)
    try:
        client.initialize()
        assert seen[0].headers["Authorization"] == "Bearer tok-123"
        assert "application/json" in seen[0].headers["Accept"]
        # 后续请求（含通知）回传 session id
        client.call_tool("echo")
        assert seen[-1].headers.get("Mcp-Session-Id") == "sess-1"
        assert seen[-1].headers["Authorization"] == "Bearer tok-123"
    finally:
        client.close()


def test_http_sse_response():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        data = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}})
        return httpx.Response(
            200,
            content=f"event: message\ndata: {data}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    transport = HttpTransport("https://mcp.example.com/mcp", http=httpx.Client(transport=httpx.MockTransport(handler)))
    client = McpClient(transport)
    try:
        result = client.call_tool("echo")
        assert result == {"ok": True}
    finally:
        client.close()


def test_http_jsonrpc_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32001, "message": "busy"}},
        )

    transport = HttpTransport("https://mcp.example.com/mcp", http=httpx.Client(transport=httpx.MockTransport(handler)))
    client = McpClient(transport)
    try:
        with pytest.raises(JsonRpcError) as exc:
            client.call_tool("echo")
        assert exc.value.code == -32001
    finally:
        client.close()


# ---------- tools/call 结果提取 ----------


def test_extract_result_items_shapes():
    page = {"id": "p1", "properties": {}}
    # structuredContent.results
    assert extract_result_items({"structuredContent": {"results": [page]}}) == [page]
    # content 文本 JSON（数组）
    assert extract_result_items({"content": [{"type": "text", "text": json.dumps([page])}]}) == [page]
    # content 文本 JSON（{results: [...]}）
    assert extract_result_items({"content": [{"type": "text", "text": json.dumps({"results": [page]})}]}) == [page]
    # 无法解析 → 空
    assert extract_result_items({"content": [{"type": "text", "text": "not json"}]}) == []
    assert extract_result_items({}) == []
