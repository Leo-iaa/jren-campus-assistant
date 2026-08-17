"""Notion MCP adapter：对接官方远程 MCP Server（mcp.notion.com/mcp）。

- 传输：MCP streamable HTTP（JSON-RPC over HTTPS，Bearer token）
- 授权：OAuth 2.0 授权码 + PKCE（见 ``oauth.py``），token 存于 data_sources.config
- 工具名可配置（官方 Notion MCP 工具：query_database / search / retrieve_page）
- 作业任务属性映射可配置（Notion 数据库结构因人而异），默认支持中英文常见属性名

不要求真实账号：传输层可注入 fake，测试全 mock（Issue #11）。
"""
from __future__ import annotations

from backend.mcp_client.models import TaskItem
from backend.mcp_client.transport import HttpTransport, McpClient, extract_result_items

DEFAULT_ENDPOINT = "https://mcp.notion.com/mcp"

DEFAULT_TOOL_QUERY_DATABASE = "query_database"
DEFAULT_TOOL_SEARCH = "search"
DEFAULT_TOOL_GET_PAGE = "retrieve_page"

# 作业任务常用属性名（可经 config["props"] 覆盖）
DEFAULT_TITLE_PROPS = ["标题", "名称", "任务", "任务名称", "Title", "title"]
DEFAULT_DEADLINE_PROPS = ["截止日期", "截止时间", "Deadline", "Due", "due", "ddl", "日期"]
DEFAULT_COURSE_PROPS = ["课程", "科目", "关联课程", "Course"]
DEFAULT_STATUS_PROPS = ["状态", "进度", "Status"]
DEFAULT_DESC_PROPS = ["描述", "详情", "备注", "说明", "Description"]

# 状态归一化（tasks.status 的 CHECK 约束只允许 todo/doing/done/cancelled）
STATUS_MAP = {
    "未开始": "todo", "待办": "todo", "todo": "todo", "not started": "todo", "not_started": "todo",
    "进行中": "doing", "in progress": "doing", "in_progress": "doing", "doing": "doing",
    "已完成": "done", "完成": "done", "done": "done", "completed": "done",
    "已取消": "cancelled", "取消": "cancelled", "cancelled": "cancelled", "canceled": "cancelled",
}


def _plain_text(prop: dict) -> str | None:
    """提取 Notion 属性中的纯文本（title / rich_text 数组）。"""
    for key in ("title", "rich_text"):
        arr = prop.get(key)
        if isinstance(arr, list):
            text = "".join(
                t.get("plain_text", "") for t in arr if isinstance(t, dict)
            ).strip()
            if text:
                return text
    return None


def _select_name(prop: dict) -> str | None:
    """提取 select / status / multi_select 的名称。"""
    for key in ("select", "status"):
        val = prop.get(key)
        if isinstance(val, dict) and val.get("name"):
            return str(val["name"])
    val = prop.get("multi_select")
    if isinstance(val, list):
        names = [v.get("name", "") for v in val if isinstance(v, dict) and v.get("name")]
        if names:
            return ", ".join(names)
    return None


def _date_value(prop: dict) -> str | None:
    """提取 date 属性的起始值（YYYY-MM-DD / ISO 时间）。"""
    val = prop.get("date")
    if isinstance(val, dict) and val.get("start"):
        return str(val["start"])
    return None


class NotionAdapter:
    """Notion 数据接入：查作业数据库 → TaskItem（tasks 表，source='notion'）。"""

    def __init__(
        self,
        config: dict,
        access_token: str | None = None,
        client: McpClient | None = None,
    ) -> None:
        self.config = config
        self.endpoint = config.get("endpoint", DEFAULT_ENDPOINT)
        self.tool_query_database = config.get("tool_query_database", DEFAULT_TOOL_QUERY_DATABASE)
        self.tool_search = config.get("tool_search", DEFAULT_TOOL_SEARCH)
        self.tool_get_page = config.get("tool_get_page", DEFAULT_TOOL_GET_PAGE)

        props = config.get("props") or {}
        self.title_props = props.get("title", DEFAULT_TITLE_PROPS)
        self.deadline_props = props.get("deadline", DEFAULT_DEADLINE_PROPS)
        self.course_props = props.get("course", DEFAULT_COURSE_PROPS)
        self.status_props = props.get("status", DEFAULT_STATUS_PROPS)
        self.description_props = props.get("description", DEFAULT_DESC_PROPS)

        self._client = client or McpClient(HttpTransport(self.endpoint, access_token=access_token))

    # ---------- 作业任务 ----------

    def fetch_tasks(self, database_id: str | None = None, max_pages: int = 50) -> list[TaskItem]:
        """查询作业数据库 → 任务列表。

        database_id 优先取参数，其次取 config["database_id"]。
        """
        db_id = database_id or self.config.get("database_id")
        if not db_id:
            raise ValueError("缺少 database_id：请在数据源 config 中配置 Notion 作业数据库 ID（config.database_id）")
        result = self._client.call_tool(
            self.tool_query_database, {"database_id": db_id, "page_size": max_pages}
        )
        return [self._to_task(row) for row in extract_result_items(result)]

    def _find_prop(self, props: dict, names: list[str]) -> dict | None:
        for name in names:
            if name in props and isinstance(props[name], dict):
                return props[name]
        return None

    def _to_task(self, page: dict) -> TaskItem:
        props = page.get("properties") or {}
        title = self._first_text(props, self.title_props)
        if not title:
            title = f"Notion 任务 {str(page.get('id', ''))[:8]}"

        deadline = None
        prop = self._find_prop(props, self.deadline_props)
        if prop is not None:
            deadline = _date_value(prop) or _plain_text(prop)

        course = None
        prop = self._find_prop(props, self.course_props)
        if prop is not None:
            course = _select_name(prop) or _plain_text(prop)

        status = "todo"
        prop = self._find_prop(props, self.status_props)
        if prop is not None:
            raw = (_select_name(prop) or _plain_text(prop) or "").strip()
            key = raw.lower() if raw.isascii() else raw
            status = STATUS_MAP.get(key, "todo")

        return TaskItem(
            title=title,
            source_ref=str(page.get("id", "")),
            description=self._first_text(props, self.description_props),
            deadline=deadline,
            course_name=course,
            status=status,
        )

    def _first_text(self, props: dict, names: list[str]) -> str | None:
        prop = self._find_prop(props, names)
        if prop is None:
            return None
        return _plain_text(prop) or _select_name(prop)

    # ---------- 通用查询 ----------

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """全文搜索 Notion 页面（返回原始 page 对象列表）。"""
        result = self._client.call_tool(self.tool_search, {"query": query, "page_size": limit})
        return extract_result_items(result)

    def fetch_page(self, page_id: str) -> dict:
        """读取页面（返回原始 page 对象）。"""
        return self._client.call_tool(self.tool_get_page, {"page_id": page_id})

    def close(self) -> None:
        self._client.close()
