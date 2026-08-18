"""Notion REST 直连客户端（api.notion.com）。

背景（Issue #26）：Notion 官方远程 MCP（mcp.notion.com/mcp）不接受
internal integration 令牌（一律 401 invalid_token，官方在
makenotion/notion-mcp-server#106 确认必须用其自身 OAuth 流程的 token），
而自建集成令牌（ntn_ / secret_）对 REST API 有效。因此 Notion 接入
从「MCP 传输」改为「REST 直连」。

- 端点：api.notion.com（v1），header 固定带 Notion-Version
- httpx 客户端可注入（测试用 MockTransport，无需真实账号）
- 错误统一转 NotionRestError（带状态码与 Notion 返回的中文信息）
"""
from __future__ import annotations

import httpx

DEFAULT_API_BASE = "https://api.notion.com"
DEFAULT_API_VERSION = "2022-06-28"


class NotionRestError(Exception):
    """Notion REST 调用失败（网络错误 / 非 2xx）。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NotionRestClient:
    """Notion REST API 客户端（仅实现本项目用到的端点）。"""

    def __init__(
        self,
        access_token: str | None = None,
        http: httpx.Client | None = None,
        api_base: str = DEFAULT_API_BASE,
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        self.access_token = access_token or ""
        self.api_base = api_base.rstrip("/")
        self.api_version = api_version
        self.http = http or httpx.Client(timeout=30.0)

    # ---------- 公开方法 ----------

    def query_database(
        self, database_id: str, filter: dict | None = None, page_size: int = 100
    ) -> list[dict]:
        """查询数据库（返回 results 列表）。"""
        body: dict = {"page_size": page_size}
        if filter:
            body["filter"] = filter
        data = self._request("POST", f"/v1/databases/{database_id}/query", body)
        return data.get("results", [])

    def create_page(self, parent_database_id: str, properties: dict) -> dict:
        """在数据库中新建页面（事件）。"""
        body = {"parent": {"database_id": parent_database_id}, "properties": properties}
        return self._request("POST", "/v1/pages", body)

    def update_page(self, page_id: str, properties: dict) -> dict:
        """更新页面属性（事件时间/标题/类型变更）。"""
        return self._request("PATCH", f"/v1/pages/{page_id}", {"properties": properties})

    def search(
        self, query: str = "", filter: dict | None = None, page_size: int = 10
    ) -> list[dict]:
        """全文搜索（返回 results 列表）。"""
        body: dict = {"query": query, "page_size": page_size}
        if filter:
            body["filter"] = filter
        data = self._request("POST", "/v1/search", body)
        return data.get("results", [])

    def retrieve_page(self, page_id: str) -> dict:
        """读取页面详情。"""
        return self._request("GET", f"/v1/pages/{page_id}")

    def close(self) -> None:
        self.http.close()

    # ---------- 内部 ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Notion-Version": self.api_version,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.api_base}{path}"
        try:
            resp = self.http.request(method, url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise NotionRestError(f"Notion API 网络错误：{exc}") from exc
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("message", "") or resp.text[:200]
            except Exception:
                detail = resp.text[:200]
            raise NotionRestError(
                f"Notion API 返回 {resp.status_code}：{detail}", status_code=resp.status_code
            )
        return resp.json()
