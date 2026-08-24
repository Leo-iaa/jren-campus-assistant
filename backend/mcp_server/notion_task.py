"""Notion 任务库写入 service：``add_task`` 后把任务写进 Notion 任务数据库。

传输：REST 直连 api.notion.com（NotionRestClient，Bearer 集成令牌，
mcp.notion.com 不接受集成令牌，见 Issue #26）。

设计要点：
- 写入前用 ``retrieve_database`` 探测数据库属性，**只写入库中真实存在的属性**。
  用户任务库可能没有「类型」select 属性（实测「任务列表」模板缺该属性），
  缺失的属性进入 ``missing_props`` 报告，不阻断任务入库；
  用户后续在 Notion 补上该属性后自动开始写入（零代码改动）。
- 属性名可配置（数据源 config.task_props，独立于日历库的 props）：
  默认中文界面常用名：任务名称 / 截止日期 / 当前状态 / 类型 / 优先级 / 备注。

时间说明：截止日期只写日期（``YYYY-MM-DD``，date-only），不带时刻。
"""
from __future__ import annotations

import os
import time

import httpx
from sqlalchemy.orm import Session

from backend.mcp_client.notion_rest import NotionRestClient
from backend.mcp_client.service import (
    _load_config,
    _save_config,
    _token_dict,
    build_oauth_client,
)
from backend.models import DataSource

#: 默认属性名（Notion 中文界面「任务列表」模板；可在数据源 config.task_props 覆盖）
DEFAULT_TASK_PROPS: dict[str, str] = {
    "title": "任务名称",
    "date": "截止日期",
    "status": "当前状态",
    "type": "类型",
    "priority": "优先级",
    "description": "备注",
}

#: status 属性初始选项名（旧版写死 To-do，实测 Notion 中文模板选项为「未开始」——
#: 现改为从数据库 schema 动态查找，见 _initial_status_name）
STATUS_INITIAL = "未开始"


class NotionTaskError(Exception):
    """任务库写入失败（缺少配置 / 授权失效 / 传输错误等）。"""


class NotionTaskWriter:
    """把任务写入 Notion 任务数据库。

    ``create_task`` 每次调用先探测数据库属性（``retrieve_database``），
    仅写入真实存在的属性；缺失属性进入 ``missing_props`` 报告。
    """

    def __init__(
        self,
        client: NotionRestClient,
        config: dict | None = None,
    ) -> None:
        self._client = client
        self.config = config or {}
        self.props = {**DEFAULT_TASK_PROPS, **(self.config.get("task_props") or {})}

    # ---------- 主流程 ----------

    def create_task(self, task: dict) -> dict:
        """写入一条任务（属性探测降级）。

        ``task`` 字段：title（必填）/ deadline（YYYY-MM-DD）/ task_type / description。

        返回 ``{"page_id": ..., "missing_props": [缺失属性名...]}``；
        传输错误抛 ``NotionTaskError``。
        """
        db_id = self._database_id()
        try:
            schema = self._client.retrieve_database(db_id)
            present = set((schema.get("properties") or {}).keys())

            properties: dict = {
                self.props["title"]: {
                    "title": [{"type": "text", "text": {"content": task["title"]}}]
                },
            }
            missing: list[str] = []

            deadline = task.get("deadline")
            if deadline:
                if self.props["date"] in present:
                    properties[self.props["date"]] = {"date": {"start": deadline}}
                else:
                    missing.append(self.props["date"])

            initial_status = self._initial_status_name(
                (schema.get("properties") or {}).get(self.props["status"])
            )
            if initial_status:
                properties[self.props["status"]] = {"status": {"name": initial_status}}

            task_type = task.get("task_type")
            if task_type:
                if self.props["type"] in present:
                    properties[self.props["type"]] = {"select": {"name": task_type}}
                else:
                    missing.append(self.props["type"])

            description = task.get("description")
            if description and self.props["description"] in present:
                properties[self.props["description"]] = {
                    "rich_text": [{"type": "text", "text": {"content": description}}]
                }

            page = self._client.create_page(db_id, properties)
        except Exception as exc:  # noqa: BLE001 —— 统一转中文异常
            raise NotionTaskError(f"Notion 任务库写入失败：{exc}") from exc
        return {"page_id": page.get("id"), "missing_props": missing}

    # ---------- 内部 ----------

    @staticmethod
    def _initial_status_name(status_prop: dict | None) -> str | None:
        """从 status 属性定义中找「待办」选项名。

        Notion status 属性返回结构：``{"type": "status", "status": {"options": [...], "groups": [...]}}``
        （groups 只是分组展示 To-do / In progress / Complete，实际可写值在
        options——如中文模板的「未开始」）。策略：优先取 To-do 组下的首个
        选项，找不到则取首个选项；无选项返回 None（不写状态属性）。
        """
        if not isinstance(status_prop, dict):
            return None
        prop = status_prop.get("status")
        if not isinstance(prop, dict):
            prop = status_prop  # 兼容直接传入 status 内部结构
        options = prop.get("options") or []
        if not options:
            return None
        groups = prop.get("groups") or []
        todo_group = next((g for g in groups if g.get("name") == "To-do"), None)
        if todo_group:
            option_ids = set(todo_group.get("option_ids") or [])
            for opt in options:
                if opt.get("id") in option_ids:
                    return opt.get("name")
        return options[0].get("name")

    def _database_id(self) -> str:
        db_id = self.config.get("task_database_id")
        if not db_id:
            raise NotionTaskError(
                "缺少 Notion 任务数据库 ID：请在数据源 config 配置 task_database_id"
                "或设置环境变量 JREN_NOTION_TASK_DB"
            )
        return db_id


def build_task_writer(
    db: Session, http: httpx.Client | None = None
) -> NotionTaskWriter | None:
    """从 data_sources 读取 Notion 配置并构造任务库写入器。

    返回 None 表示未绑定 Notion 数据源（add_task 静默跳过任务库写入）；
    已绑定但未授权 / 缺任务库 ID → 抛 NotionTaskError。
    """
    source = db.query(DataSource).filter(DataSource.source_type == "notion").first()
    if source is None:
        return None

    config = _load_config(source)
    tokens = config.get("tokens") or {}
    access_token = tokens.get("access_token")
    if not access_token:
        raise NotionTaskError(
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
            raise NotionTaskError("Notion token 已过期且无 refresh_token，请重新授权")
        try:
            token = build_oauth_client(config, http=http).refresh(refresh_token)
        except httpx.HTTPError as exc:
            raise NotionTaskError(f"Notion token 刷新失败：{exc}") from exc
        config["tokens"] = _token_dict(token)
        _save_config(source, config)
        access_token = token.access_token

    db_id = config.get("task_database_id") or os.environ.get("JREN_NOTION_TASK_DB")
    if not db_id:
        raise NotionTaskError(
            "缺少 Notion 任务数据库 ID：请在数据源 config 配置 task_database_id"
            "或设置环境变量 JREN_NOTION_TASK_DB"
        )
    # 环境变量兜底值写回 config，writer 统一从 config 取（构造与写入保持一致）
    config["task_database_id"] = db_id

    client = NotionRestClient(access_token=access_token, http=http)
    return NotionTaskWriter(client=client, config=config)
