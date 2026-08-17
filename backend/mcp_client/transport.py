"""MCP 传输层：JSON-RPC 2.0 客户端（stdio / streamable HTTP）。

实现 MCP 协议所需的最小客户端子集：
- ``initialize`` / ``notifications/initialized``
- ``tools/list`` / ``tools/call``

传输实现可注入替换（测试使用 FakeJsonRpcTransport），
真实接入（mcp.notion.com/mcp、obsidian-mcp-server）时无需改动 adapter。
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from typing import Protocol

import httpx

# 协议版本：obsidian-mcp-server 等主流实现均兼容 2024-11-05
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
STDIO_READ_TIMEOUT = 60.0


class JsonRpcError(Exception):
    """JSON-RPC error 响应。"""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"JSON-RPC 错误 {code}: {message}")


class Transport(Protocol):
    """传输通道接口：子类实现 _post / _notify / close。"""

    def _post(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict: ...
    def _notify(self, method: str, params: dict | None = None) -> None: ...
    def close(self) -> None: ...


class McpClient:
    """基于任意 Transport 的 MCP 客户端（initialize / list_tools / call_tool）。"""

    def __init__(self, transport: Transport, protocol_version: str = DEFAULT_PROTOCOL_VERSION) -> None:
        self._transport = transport
        self._protocol_version = protocol_version

    def initialize(self) -> dict:
        """MCP 握手：initialize + notifications/initialized。"""
        result = self._transport._post(
            "initialize",
            {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "jren-campus-assistant", "version": "0.1.0"},
            },
        )
        self._transport._notify("notifications/initialized", {})
        return result

    def list_tools(self) -> list[dict]:
        """tools/list → 服务器能力清单。"""
        return self._transport._post("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """tools/call → 工具调用结果（含 content / structuredContent / isError）。"""
        return self._transport._post("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        self._transport.close()


class StdioTransport:
    """MCP stdio 传输：子进程 stdin/stdout 逐行 JSON-RPC（obsidian-mcp-server 等）。

    - 请求按行写入子进程 stdin
    - 后台线程读 stdout 并放入队列；响应按 id 匹配，通知类消息自动忽略
    """

    def __init__(
        self,
        command: list[str],
        cwd: str | None = None,
        timeout: float = STDIO_READ_TIMEOUT,
    ) -> None:
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=cwd,
        )
        self._timeout = timeout
        self._next_id = 0
        self._queue: queue.Queue[dict] = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict):
                self._queue.put(msg)

    def _post(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self._next_id += 1
        request: dict = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            request["params"] = params
        self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

        deadline = time.monotonic() + (timeout or self._timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JsonRpcError(-32000, "等待 MCP 响应超时")
            try:
                msg = self._queue.get(timeout=remaining)
            except queue.Empty:
                continue
            if "id" not in msg or msg["id"] != self._next_id:
                continue  # 通知 / 无关响应 → 忽略
            if "error" in msg:
                err = msg["error"]
                raise JsonRpcError(err.get("code", -32603), err.get("message", "未知错误"))
            return msg.get("result", {})

    def _notify(self, method: str, params: dict | None = None) -> None:
        request: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params
        self._proc.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def close(self) -> None:
        try:
            self._proc.terminate()
        except Exception:
            pass


class HttpTransport:
    """MCP streamable HTTP 传输：JSON-RPC over HTTPS（mcp.notion.com/mcp）。

    遵循 MCP 规范：Accept 同时声明 application/json 与 text/event-stream；
    响应头 ``Mcp-Session-Id`` 会在后续请求中自动回传。
    """

    def __init__(
        self,
        endpoint: str,
        access_token: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._endpoint = endpoint
        self._access_token = access_token
        self._session_id: str | None = None
        self._http = http or httpx.Client(timeout=timeout)
        self._next_id = 0

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self._next_id += 1
        request: dict = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            request["params"] = params
        try:
            resp = self._http.post(self._endpoint, json=request, headers=self._headers())
        except httpx.HTTPError as exc:
            raise JsonRpcError(-32000, f"HTTP 请求失败：{exc}") from exc
        if "mcp-session-id" in resp.headers:
            self._session_id = resp.headers["mcp-session-id"]
        body = self._parse_body(resp)
        if "error" in body:
            err = body["error"]
            raise JsonRpcError(err.get("code", -32603), err.get("message", "未知错误"))
        return body.get("result", {})

    def _parse_body(self, resp: httpx.Response) -> dict:
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for line in resp.text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    try:
                        return json.loads(line[5:].strip())
                    except ValueError:
                        continue
            raise JsonRpcError(-32000, "SSE 响应中没有可解析的数据")
        try:
            return resp.json()
        except ValueError as exc:
            raise JsonRpcError(-32000, f"响应不是合法 JSON：{resp.text[:200]}") from exc

    def _notify(self, method: str, params: dict | None = None) -> None:
        request: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params
        try:
            self._http.post(self._endpoint, json=request, headers=self._headers())
        except httpx.HTTPError:
            pass  # 通知类消息允许失败（fire-and-forget）

    def close(self) -> None:
        self._http.close()


def extract_result_items(result: dict) -> list[dict]:
    """从 tools/call 结果中提取对象列表。

    优先取 ``structuredContent``（Notion MCP 等服务器的结构化输出），
    其次解析 ``content`` 中的 JSON 文本；两种形态都兼容
    ``{"results": [...]}`` 与裸数组。
    """
    sc = result.get("structuredContent")
    if isinstance(sc, list):
        return [d for d in sc if isinstance(d, dict)]
    if isinstance(sc, dict):
        if isinstance(sc.get("results"), list):
            return [d for d in sc["results"] if isinstance(d, dict)]
        return [d for d in sc.values() if isinstance(d, dict)] if sc else []

    text = "".join(
        c.get("text", "")
        for c in result.get("content", [])
        if isinstance(c, dict) and c.get("type") == "text"
    ).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return [d for d in data["results"] if isinstance(d, dict)]
    return []
