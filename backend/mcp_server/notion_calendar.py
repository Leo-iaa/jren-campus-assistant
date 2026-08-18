"""Notion Calendar 写入 service：plan_items 幂等写入 Notion 日程数据库。

设计依据 docs/vision.md「提醒链路（方案 A）」：Notion Calendar 事件提醒
作为 WorkBuddy 微信推送的双保险（电脑关机时云端兜底）。

复用 ``backend/mcp_client/``：
- 传输层 ``McpClient`` + ``HttpTransport``（backend/mcp_client/transport.py）
- OAuth token 管理（backend/mcp_client/service.py：过期自动刷新并写回 config）
- 工具：query_database（查当日已有事件）/ create_page（新建）/ update_page（更新）

幂等策略：按「日期（date 属性过滤当日）+ 标题精确匹配」定位已有事件
- 不存在 → create_page（属性含日期起止 + 08:00 提醒 + 类型 select）
- 存在但时间/标题/类型有变化 → update_page
- 完全一致 → 跳过（unchanged）

属性名可配置（数据源 config.props，默认中文界面常用名：名称 / 日期 / 类型）。

时间说明：日期时间写入带 ``+08:00`` 偏移（Notion API 对无偏移值按 UTC 解析，
会导致 +8 时区显示偏差）；提醒用绝对时间 ``08:00``，事件当天触发。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy.orm import Session

from backend.mcp_client.notion import DEFAULT_ENDPOINT
from backend.mcp_client.service import (
    _load_config,
    _save_config,
    _token_dict,
    build_oauth_client,
)
from backend.mcp_client.transport import HttpTransport, JsonRpcError, McpClient, extract_result_items
from backend.models import DataSource, PlanItem

#: 默认属性名（Notion 中文界面；可在数据源 config.props 覆盖）
DEFAULT_PROPS: dict[str, str] = {
    "title": "名称",
    "date": "日期",
    "type": "类型",
}

#: 事件提醒时间（绝对时间，事件当天触发；方案 A 双保险）
REMINDER_TIME = "08:00"


class NotionCalendarError(Exception):
    """日历写入失败（缺少配置 / 授权失效 / 传输错误等）。"""


@dataclass
class CalendarSyncResult:
    """一次日历同步的结果统计。"""

    created: int = 0
    updated: int = 0
    unchanged: int = 0


class NotionCalendarWriter:
    """把 plan_items 幂等写入 Notion 日程数据库。

    传输层可注入（测试使用 FakeJsonRpcTransport，不需要真实账号）。
    """

    def __init__(
        self,
        client: McpClient,
        config: dict | None = None,
    ) -> None:
        self._client = client
        self.config = config or {}
        self.props = {**DEFAULT_PROPS, **(self.config.get("props") or {})}

    # ---------- 主流程 ----------

    def sync_plan_to_calendar(self, db: Session, plan_date: date) -> CalendarSyncResult:
        """把某日 plan_items 同步到 Notion 日程数据库（幂等）。"""
        iso = plan_date.isoformat()
        items = (
            db.query(PlanItem)
            .filter(PlanItem.date == iso)
            .order_by(PlanItem.start_time)
            .all()
        )
        if not items:
            return CalendarSyncResult()

        existing = self._find_existing(iso)
        by_title = {self._event_title(page): page for page in existing}

        created = updated = unchanged = 0
        for item in items:
            page = by_title.get(item.title)
            if page is None:
                self._call(
                    "create_page",
                    {
                        "parent": {"database_id": self._database_id()},
                        "properties": self._build_properties(item),
                    },
                )
                created += 1
            elif self._page_matches(page, item):
                unchanged += 1
            else:
                self._call(
                    "update_page",
                    {
                        "page_id": page.get("id"),
                        "properties": self._build_properties(item),
                    },
                )
                updated += 1

        return CalendarSyncResult(created=created, updated=updated, unchanged=unchanged)

    # ---------- 内部 ----------

    def _database_id(self) -> str:
        db_id = self.config.get("calendar_database_id")
        if not db_id:
            raise NotionCalendarError(
                "缺少 Notion 日程数据库 ID：请在数据源 config 配置 calendar_database_id"
                "或设置环境变量 JREN_NOTION_CALENDAR_DB"
            )
        return db_id

    def _find_existing(self, iso: str) -> list[dict]:
        """查询当日已有事件（date 属性过滤，属性名可配置）。"""
        result = self._call(
            "query_database",
            {
                "database_id": self._database_id(),
                "page_size": 100,
                "filter": {
                    "property": self.props["date"],
                    "date": {"equals": iso},
                },
            },
        )
        return extract_result_items(result)

    def _build_properties(self, item: PlanItem) -> dict:
        """构造 Notion 事件属性：名称 / 日期（起止 + 08:00 提醒）/ 类型。"""
        return {
            self.props["title"]: {
                "title": [{"type": "text", "text": {"content": item.title}}]
            },
            self.props["date"]: {
                "date": {
                    "start": f"{item.date}T{item.start_time}:00+08:00",
                    "end": f"{item.date}T{item.end_time}:00+08:00",
                    "reminder": {"time": REMINDER_TIME},
                }
            },
            self.props["type"]: {"select": {"name": item.item_type}},
        }

    def _call(self, tool: str, arguments: dict) -> dict:
        """调用 Notion MCP 工具，传输错误统一转中文异常。"""
        try:
            return self._client.call_tool(tool, arguments)
        except JsonRpcError as exc:
            raise NotionCalendarError(f"Notion MCP 调用失败（{tool}）：{exc}") from exc

    # ---------- 幂等比对 ----------

    def _event_title(self, page: dict) -> str:
        """从已有事件提取标题（title 属性纯文本拼接）。"""
        props = page.get("properties") or {}
        prop = props.get(self.props["title"]) or {}
        for key in ("title", "rich_text"):
            arr = prop.get(key)
            if isinstance(arr, list):
                text = "".join(
                    t.get("plain_text", "") for t in arr if isinstance(t, dict)
                ).strip()
                if text:
                    return text
        return ""

    def _page_matches(self, page: dict, item: PlanItem) -> bool:
        """比对已有事件与目标计划项是否一致（仅比较我们写入的字段）。"""
        props = page.get("properties") or {}
        title = self._event_title(page)
        if title != item.title:
            return False

        date_prop = (props.get(self.props["date"]) or {}).get("date") or {}
        start = str(date_prop.get("start", ""))
        # 容忍时区后缀差异：仅比较到分钟（YYYY-MM-DDTHH:MM）
        expected_start = f"{item.date}T{item.start_time}"
        if not start.startswith(expected_start):
            return False

        type_prop = (props.get(self.props["type"]) or {}).get("select") or {}
        return type_prop.get("name") == item.item_type


def build_writer(db: Session, http: httpx.Client | None = None) -> NotionCalendarWriter | None:
    """从 data_sources 读取 Notion 配置并构造写入器。

    返回 None 表示未绑定 Notion 数据源（确认流程静默跳过日历同步）；
    已绑定但未授权 / 缺日历数据库 ID / token 刷新失败 → 抛 NotionCalendarError。
    """
    source = db.query(DataSource).filter(DataSource.source_type == "notion").first()
    if source is None:
        return None

    config = _load_config(source)
    tokens = config.get("tokens") or {}
    access_token = tokens.get("access_token")
    if not access_token:
        raise NotionCalendarError(
            "Notion 未授权：请先通过 POST /api/data-sources/notion/oauth/start 完成授权"
        )

    # token 过期 → 自动刷新（成功后写回数据源 config）
    try:
        expires_at = float(tokens["expires_at"]) if tokens.get("expires_at") else None
    except (TypeError, ValueError):
        expires_at = None
    if expires_at is not None and expires_at < time.time() + 60:
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise NotionCalendarError("Notion token 已过期且无 refresh_token，请重新授权")
        try:
            token = build_oauth_client(config, http=http).refresh(refresh_token)
        except httpx.HTTPError as exc:
            raise NotionCalendarError(f"Notion token 刷新失败：{exc}") from exc
        config["tokens"] = _token_dict(token)
        _save_config(source, config)
        access_token = token.access_token

    db_id = config.get("calendar_database_id") or os.environ.get("JREN_NOTION_CALENDAR_DB")
    if not db_id:
        raise NotionCalendarError(
            "缺少 Notion 日程数据库 ID：请在数据源 config 配置 calendar_database_id"
            "或设置环境变量 JREN_NOTION_CALENDAR_DB"
        )
    # 环境变量兜底值写回 config，writer 统一从 config 取（构造与同步保持一致）
    config["calendar_database_id"] = db_id

    client = McpClient(
        HttpTransport(config.get("endpoint", DEFAULT_ENDPOINT), access_token=access_token)
    )
    return NotionCalendarWriter(client=client, config=config)
