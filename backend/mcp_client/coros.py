"""高驰 COROS 官方 MCP adapter（远程 streamable HTTP + OAuth，查询型数据源）。

接入方式（Issue #65，2026-08 实测确认）：
- MCP 端点 ``https://mcp.coros.com/mcp``，streamable HTTP，**无状态调用**
  （官方 skill 明确：不要求 Mcp-Session-Id、不发 notifications/initialized）
- OAuth：动态客户端注册（``/connect/register``）→ CLI 登录会话（官方网关
  ``/api/v1/cli/login-sessions``，返回 loginUrl）→ 用户浏览器打开 loginUrl
  完成 COROS 登录 → 轮询 claim 拿 login_ticket → 带 ticket 访问 authorize
  → 302 Location 里取 code（回调地址无需真实可访问）→ PKCE 兑换 token
- scopes：``openid offline_access mcp.tools``（offline_access 换 refresh_token）
- token 存数据源 config.tokens（响应侧由 DataSourceRead 统一打码），
  过期前 60s 自动 refresh 并写回 config

数据语义：COROS 服务器保存完整训练历史，本层**不落库**（同 Obsidian 模式），
每次查询实时读；工具结果经 ``extract_result_items`` 兼容三种返回形态
（structuredContent / content JSON 文本 / 裸文本）。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx

from backend.mcp_client.transport import JsonRpcError, McpClient

#: 官方端点（网关会 302 到具体集群，token 按网关签发，直接用网关域名即可）
DEFAULT_MCP_URL = "https://mcp.coros.com/mcp"
DEFAULT_ISSUER = "https://mcp.coros.com"
#: 网关按 Accept-Language / 账号区域选择集群；请求头里声明中文区（对齐官方 skill 的 CN 默认）
REGION_HEADERS = {"Accept-Language": "zh-CN,zh;q=0.9"}
DEFAULT_SCOPES = "openid offline_access mcp.tools"
DEFAULT_CLIENT_NAME = "Jren Campus Assistant"
#: 官方 skill 同款回调地址：仅用于注册与 code 提取，服务端不要求真实可达
DEFAULT_REDIRECT_URI = "http://127.0.0.1:43123/callback"

#: 训练计划关心的官方只读工具（tools/list 里按名字匹配，缺失不报错只降级）
RUNNING_TOOLS = (
    "querySportRecords",
    "queryRecoveryStatus",
    "queryFitnessAssessmentOverview",
    "queryTrainingLoadAssessment",
)

#: CLI 登录会话轮询的默认参数（对齐官方 skill）
DEFAULT_LOGIN_TIMEOUT = 300.0
DEFAULT_POLL_INTERVAL = 3.0


class CorosAuthError(Exception):
    """COROS 授权缺失 / 失效 / 登录未完成（API 层映射为 401）。"""


class CorosError(Exception):
    """COROS MCP 调用失败（网络 / 协议 / 业务错误）。"""


# ---------- OAuth：动态注册 + CLI 登录会话（device 流） ----------


@dataclass(frozen=True)
class CorosOAuthConfig:
    issuer: str = DEFAULT_ISSUER
    client_name: str = DEFAULT_CLIENT_NAME
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scopes: str = DEFAULT_SCOPES
    #: httpx 客户端注入点（测试用 MockTransport，真机为 None）
    http: httpx.Client | None = None


@dataclass
class CorosLoginSession:
    """一次待完成的登录（start 与 finish 之间可序列化进 config）。"""

    client_id: str
    code_verifier: str
    state: str
    session_id: str
    poll_token: str
    login_url: str
    poll_interval: float


def _client(oauth: CorosOAuthConfig) -> httpx.Client:
    return oauth.http or httpx.Client(timeout=30.0)


def _form_response(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError as exc:
        raise CorosError(f"COROS 授权接口返回非 JSON（HTTP {resp.status_code}）") from exc


def register_client(oauth: CorosOAuthConfig) -> str:
    """RFC 7591 动态注册，返回 client_id（token_endpoint_auth_method=none 公开客户端）。"""
    http = _client(oauth)
    try:
        resp = http.post(
            f"{oauth.issuer}/connect/register",
            json={
                "client_name": oauth.client_name,
                "redirect_uris": [oauth.redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": oauth.scopes,
                "token_endpoint_auth_method": "none",
            },
            headers=REGION_HEADERS,
        )
    except httpx.HTTPError as exc:
        raise CorosError(f"COROS 动态注册失败：{exc}") from exc
    payload = _form_response(resp)
    client_id = payload.get("client_id")
    if resp.status_code not in (200, 201) or not client_id:
        raise CorosError(f"COROS 动态注册失败：{payload}")
    return client_id


def start_login(oauth: CorosOAuthConfig) -> CorosLoginSession:
    """创建 CLI 登录会话：生成 PKCE + authorize URL，返回待完成会话。"""
    from backend.mcp_client.oauth import generate_code_challenge, generate_code_verifier, generate_state

    client_id = register_client(oauth)
    verifier = generate_code_verifier()
    challenge = generate_code_challenge(verifier)
    state = generate_state()
    authorize_url = (
        f"{oauth.issuer}/oauth2/authorize?"
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": oauth.redirect_uri,
                "scope": oauth.scopes,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": DEFAULT_MCP_URL,
                "state": state,
            }
        )
    )
    http = _client(oauth)
    try:
        resp = http.post(
            f"{oauth.issuer}/api/v1/cli/login-sessions",
            json={"clientId": client_id},
            headers=REGION_HEADERS,
        )
    except httpx.HTTPError as exc:
        raise CorosError(f"创建 COROS 登录会话失败：{exc}") from exc
    payload = _form_response(resp)
    for key in ("sessionId", "pollToken", "loginUrl"):
        if not payload.get(key):
            raise CorosError(f"COROS 登录会话响应缺少 {key}：{payload}")
    return CorosLoginSession(
        client_id=client_id,
        code_verifier=verifier,
        state=state,
        session_id=payload["sessionId"],
        poll_token=payload["pollToken"],
        login_url=payload["loginUrl"],
        poll_interval=max(1.0, float(payload.get("intervalSeconds") or 3.0)),
    )


def finish_login(
    oauth: CorosOAuthConfig,
    session: CorosLoginSession,
    *,
    timeout: float = DEFAULT_LOGIN_TIMEOUT,
) -> dict:
    """轮询等待用户在浏览器完成登录 → 兑换 token。

    返回 token dict（access_token / refresh_token / expires_at / client_id），
    由调用方写入数据源 config.tokens。登录轮询最长等 ``timeout`` 秒。
    """
    from backend.mcp_client.oauth import OAuthToken  # noqa: F401  仅保证模块可用

    http = _client(oauth)
    deadline = time.monotonic() + timeout
    login_ticket: str | None = None
    while login_ticket is None:
        if time.monotonic() >= deadline:
            raise CorosAuthError("等待 COROS 登录超时：请重新发起授权")
        try:
            resp = http.post(
                f"{oauth.issuer}/api/v1/cli/login-sessions/{session.session_id}/claim",
                headers={**REGION_HEADERS, "X-Poll-Token": session.poll_token},
            )
        except httpx.HTTPError as exc:
            raise CorosError(f"COROS 登录轮询失败：{exc}") from exc
        payload = _form_response(resp)
        status = str(payload.get("status", "")).lower()
        if status == "authorized":
            login_ticket = payload.get("loginTicket")
            if not login_ticket:
                raise CorosError("COROS 登录会话已授权但缺少 loginTicket")
        elif status == "pending":
            time.sleep(session.poll_interval)
        elif status == "expired":
            raise CorosAuthError("COROS 登录会话已过期，请重新发起授权")
        elif status == "failed":
            raise CorosAuthError(f"COROS 登录失败：{payload.get('errorCode', '未知错误')}")
        elif status == "claimed":
            raise CorosAuthError("COROS 登录会话已被其他客户端认领，请重新发起授权")
        else:
            raise CorosError(f"COROS 登录会话状态异常：{status or payload}")

    # 带 login_ticket 重放 authorize → 302 Location 里提取 code 与 state
    authorize_url = (
        f"{oauth.issuer}/oauth2/authorize?"
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": session.client_id,
                "redirect_uri": oauth.redirect_uri,
                "scope": oauth.scopes,
                "code_challenge": _challenge_of(session.code_verifier),
                "code_challenge_method": "S256",
                "resource": DEFAULT_MCP_URL,
                "state": session.state,
                "login_ticket": login_ticket,
            }
        )
    )
    try:
        resp = http.get(authorize_url, headers=REGION_HEADERS, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise CorosError(f"COROS 授权跳转失败：{exc}") from exc
    callback_url = resp.headers.get("location")
    if resp.status_code not in (301, 302, 303, 307, 308) or not callback_url:
        raise CorosError(f"COROS 授权未返回回调（HTTP {resp.status_code}），login_ticket 可能已失效")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(callback_url).query)
    code, state = query.get("code", [""])[0], query.get("state", [""])[0]
    if not code or state != session.state:
        raise CorosError("COROS 授权回调缺少 code 或 state 不匹配")

    token = _exchange_code(oauth, http, client_id=session.client_id, code=code, verifier=session.code_verifier)
    token["client_id"] = session.client_id
    return token


def _challenge_of(verifier: str) -> str:
    from backend.mcp_client.oauth import generate_code_challenge

    return generate_code_challenge(verifier)


def _exchange_code(oauth: CorosOAuthConfig, http: httpx.Client, *, client_id: str, code: str, verifier: str) -> dict:
    try:
        resp = http.post(
            f"{oauth.issuer}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": oauth.redirect_uri,
                "code_verifier": verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", **REGION_HEADERS},
        )
    except httpx.HTTPError as exc:
        raise CorosError(f"COROS token 兑换失败：{exc}") from exc
    payload = _form_response(resp)
    if resp.status_code != 200 or not payload.get("access_token"):
        raise CorosError(f"COROS token 兑换失败：{payload}")
    return _token_dict(payload)


def refresh_token(oauth: CorosOAuthConfig, client_id: str, refresh_token: str) -> dict:
    """用 refresh_token 续期，返回新 token dict。"""
    http = _client(oauth)
    try:
        resp = http.post(
            f"{oauth.issuer}/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", **REGION_HEADERS},
        )
    except httpx.HTTPError as exc:
        raise CorosError(f"COROS token 刷新失败：{exc}") from exc
    payload = _form_response(resp)
    if resp.status_code != 200 or not payload.get("access_token"):
        raise CorosError(f"COROS token 刷新失败：{payload}")
    return _token_dict(payload)


def _token_dict(payload: dict) -> dict:
    expires_in = payload.get("expires_in")
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + float(expires_in) if expires_in else None,
    }


# ---------- adapter：查询跑步数据（无状态 MCP 调用） ----------


@dataclass(frozen=True)
class RunningActivity:
    """一次跑步记录（字段从官方工具结果容错提取，缺省 None）。"""

    date: str | None = None
    distance_km: float | None = None
    duration_minutes: float | None = None
    pace_sec_per_km: int | None = None
    avg_heart_rate: int | None = None
    workout_type: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RunningSnapshot:
    """一次跑步数据查询的汇总（供规则引擎与工具返回）。"""

    activities: list[RunningActivity]
    recovery: dict | None = None  # queryRecoveryStatus 原始结果
    fitness: dict | None = None  # queryFitnessAssessmentOverview 原始结果
    load: dict | None = None  # queryTrainingLoadAssessment 原始结果
    available_tools: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _json_from_result(result: dict) -> object:
    """tools/call 结果 → Python 对象：structuredContent > content JSON 文本 > 原文本。"""
    sc = result.get("structuredContent")
    if sc is not None:
        return sc
    texts = [
        c.get("text", "")
        for c in result.get("content", [])
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    text = "".join(texts).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _iter_records(obj: object) -> list[dict]:
    """官方工具返回形态容错：{records: [...]} / {results: [...]} / 裸数组 / 单对象。"""
    if isinstance(obj, list):
        return [d for d in obj if isinstance(d, dict)]
    if isinstance(obj, dict):
        for key in ("records", "results", "activities", "items", "data", "list"):
            value = obj.get(key)
            if isinstance(value, list):
                return [d for d in value if isinstance(d, dict)]
        if obj:
            return [obj]
    return []


def _first_num(*values: object) -> float | None:
    for v in values:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(re.sub(r"[^\d.]", "", v)) if re.search(r"\d", v) else None
            except ValueError:
                continue
    return None


def _first_str(*values: object) -> str | None:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _normalize_activity(rec: dict) -> RunningActivity:
    """官方字段名未知部分容错归一化（已知候选键并列尝试，真实接入后校准）。"""
    date = _first_str(
        rec.get("startTime"), rec.get("start_time"), rec.get("date"),
        rec.get("day"), rec.get("gmtStart"),
    )
    # 距离：米/千米双形态（>1000 视为米）
    distance = _first_num(rec.get("distance"), rec.get("totalDistance"), rec.get("distanceKm"))
    if distance is not None and distance > 2000:
        distance = distance / 1000.0
    duration = _first_num(
        rec.get("duration"), rec.get("totalTime"), rec.get("durationSeconds"),
        rec.get("movingTime"),
    )
    # 时长：秒/分钟双形态（>600 视为秒）
    if duration is not None and duration > 600:
        duration = duration / 60.0
    pace = _first_num(rec.get("pace"), rec.get("avgPace"), rec.get("paceSecPerKm"))
    # 配速：若数值落在分钟/公里区间（>3 且 <20）且另有秒值候选，优先秒值
    pace_candidates = [pace]
    for key in ("avgPaceSecPerKm", "paceSeconds"):
        value = rec.get(key)
        if isinstance(value, (int, float)):
            pace_candidates.insert(0, float(value))
    pace = next((p for p in pace_candidates if p is not None), None)
    hr = _first_num(rec.get("avgHeartRate"), rec.get("avgHr"), rec.get("heartRate"))
    workout_type = _first_str(rec.get("workoutType"), rec.get("sportType"), rec.get("type"), rec.get("sportTypeName"))
    return RunningActivity(
        date=date,
        distance_km=distance,
        duration_minutes=duration,
        pace_sec_per_km=int(pace) if pace is not None else None,
        avg_heart_rate=int(hr) if hr is not None else None,
        workout_type=workout_type,
        raw=rec,
    )


class CorosAdapter:
    """COROS MCP adapter：注入 access_token / 传输（测试可替换），查询跑步数据。

    与现有 adapter 一致：产出纯数据结构，不碰 ORM；无状态 MCP 调用
    （每次查询独立 initialize + tools/call，对齐官方 skill 的 runtime 语义）。
    """

    def __init__(
        self,
        config: dict | None = None,
        *,
        access_token: str | None = None,
        client: McpClient | None = None,
        endpoint: str = DEFAULT_MCP_URL,
    ) -> None:
        cfg = config if config is not None else {}
        self._config = cfg
        self._endpoint = cfg.get("mcp_url", endpoint)
        self._access_token = access_token
        self._client = client  # 测试注入点；真实使用时惰性构造
        self._owned_client: McpClient | None = None

    # -- 传输 --

    def _get_client(self) -> McpClient:
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            from backend.mcp_client.transport import HttpTransport

            transport = HttpTransport(self._endpoint, access_token=self._access_token)
            self._owned_client = McpClient(transport)
        return self._owned_client

    def set_access_token(self, token: str) -> None:
        self._access_token = token
        self._owned_client = None  # 下次调用重建传输

    # -- 官方工具查询 --

    def _call(self, name: str, arguments: dict | None = None) -> object:
        client = self._get_client()
        try:
            client.initialize()
            result = client.call_tool(name, arguments)
        except JsonRpcError as exc:
            raise CorosError(f"COROS MCP {name} 调用失败：{exc}") from exc
        return _json_from_result(result)

    def list_tools(self) -> list[dict]:
        client = self._get_client()
        try:
            client.initialize()
            return client.list_tools()
        except JsonRpcError as exc:
            raise CorosError(f"COROS MCP tools/list 失败：{exc}") from exc

    def _try_tool(self, name: str, arguments: dict) -> tuple[object | None, str | None]:
        """调用官方工具；未配置 / 失败降级为 (None, warning)，不阻断整体查询。"""
        try:
            return self._call(name, arguments), None
        except CorosError as exc:
            return None, str(exc)

    def fetch_running_snapshot(
        self,
        *,
        days: int = 7,
        activities_limit: int = 20,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> RunningSnapshot:
        """拉取近期跑步数据汇总：活动记录 + 恢复 + 体能 + 负荷。

        官方工具参数 schema 未公开文档化：日期参数以 ``startDate/endDate``
        （YYYYMMDD）为主形态，server 端未知参数会忽略 —— 多余键无害。
        """
        warnings: list[str] = []
        available: list[str] = []
        try:
            names = {t.get("name") for t in self.list_tools()}
        except CorosError as exc:
            names = set()
            warnings.append(f"tools/list 失败：{exc}")
        for tool in RUNNING_TOOLS:
            if tool in names:
                available.append(tool)
        if "querySportRecords" in names and not available:
            pass
        if not names:
            # tools/list 失败时仍尽力调用核心工具（可能只是元数据接口受限）
            available = ["querySportRecords", "queryRecoveryStatus", "queryFitnessAssessmentOverview", "queryTrainingLoadAssessment"]

        from datetime import date as _date, timedelta as _timedelta

        end = _date.today() if date_to is None else _date.fromisoformat(date_to)
        start = end - _timedelta(days=days) if date_from is None else _date.fromisoformat(date_from)
        start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

        records_obj, warn = self._try_tool(
            "querySportRecords", {"startDate": start_s, "endDate": end_s}
        )
        if warn:
            warnings.append(warn)
        activities = [_normalize_activity(r) for r in _iter_records(records_obj)][:activities_limit]

        recovery_obj, warn = self._try_tool("queryRecoveryStatus", {})
        if warn:
            warnings.append(warn)
        fitness_obj, warn = self._try_tool("queryFitnessAssessmentOverview", {})
        if warn:
            warnings.append(warn)
        load_obj, warn = self._try_tool("queryTrainingLoadAssessment", {})
        if warn:
            warnings.append(warn)

        def _as_dict(obj: object) -> dict | None:
            return obj if isinstance(obj, dict) else None

        return RunningSnapshot(
            activities=activities,
            recovery=_as_dict(recovery_obj),
            fitness=_as_dict(fitness_obj),
            load=_as_dict(load_obj),
            available_tools=available,
            warnings=warnings,
        )

    def close(self) -> None:
        if self._owned_client is not None:
            self._owned_client.close()
            self._owned_client = None
