"""MCP Server 暴露层：把后端能力包装为 MCP 工具（QClaw 等客户端可调用）。

- 传输：Streamable HTTP，挂载 ``/mcp`` 路径（接线见 ``backend/main.py``）
- 工具（8 个，对齐 docs/mcp-server.md）：
  generate_tomorrow_plan / get_today_plan_preview / confirm_plan /
  adjust_plan_item / get_courses / get_tasks / get_reviews / mark_done
- 每个工具调用使用独立数据库会话（``SessionLocal``），互不干扰；
  ``db_factory`` 可注入（测试指向临时数据库）
- 工具返回 JSON 文本（ensure_ascii=False），便于 LLM 客户端直接阅读；
  出错返回 ``{"error": "..."}``，不让异常透出到协议层

实现约定：业务逻辑全部在 ``backend/mcp_server/service.py``，
本模块只做「参数 → 会话 → 调用 → 序列化」的薄封装。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any

from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import SessionLocal
from backend.mcp_server.notion_calendar import NotionCalendarError, build_writer
from backend.mcp_server.service import (
    adjust_plan_item,
    confirm_plan,
    generate_plan,
    list_courses,
    list_reviews,
    list_tasks,
    mark_done,
    parse_date,
    preview_plan_text,
    shanghai_today,
    tomorrow,
)

#: 工具说明（QClaw 等客户端据此理解用法）
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "generate_tomorrow_plan": (
        "生成次日计划草案（默认明日，可指定日期 YYYY-MM-DD）。"
        "返回：date / placed（放置项数）/ dropped（放不下的项目）/ skipped（跳过的项目）。"
    ),
    "get_today_plan_preview": (
        "获取今日计划文本（默认今天，可指定日期），适合直接推送微信。"
        "包含课程 / 作业 / 复习 / 杂项时间轴与确认状态。"
    ),
    "confirm_plan": (
        "确认某日计划（YYYY-MM-DD，必填）：draft/adjusted 项转为 confirmed，"
        "写入版本快照，并同步写入 Notion 日历（带 08:00 提醒，双保险）。"
    ),
    "adjust_plan_item": (
        "调整单个计划项：item_id + 新 start_time/end_time（HH:MM），可选新 title。"
        "与同日其他项时间冲突会报错。"
    ),
    "get_courses": "查询课程列表（含 S/A/B/C 档位）。",
    "get_tasks": "查询作业任务列表，可按 status 过滤（todo/doing/done/cancelled）。",
    "get_reviews": "查询复习计划列表，可按 due_date（YYYY-MM-DD）过滤。",
    "mark_done": (
        "标记计划项完成：item_id 必填，actual_minutes 为实际耗时（分钟，可选）。"
        "task/review 项记录「预估 vs 实际」校准；review 项联动复习计划置 done。"
    ),
}


def build_mcp_server(
    db_factory: Callable[[], Session] | None = None,
) -> MCPServer:
    """构造 MCP Server（工具注册 + 描述），默认使用全局 SessionLocal。"""
    factory: Callable[[], Session] = db_factory or SessionLocal

    @contextmanager
    def session_scope():
        """每个工具调用一个独立会话：出错回滚，结束后关闭。"""
        session = factory()
        try:
            yield session
            session.commit()  # service 层已提交；此处兜底，无变更时为空操作
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def safe(fn: Callable[..., str]) -> Callable[..., str]:
        """工具守卫：异常转为 {"error": ...} JSON 文本。"""

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 —— 工具层不允许异常透出协议
                return json.dumps({"error": str(exc)}, ensure_ascii=False)

        return wrapper

    server = MCPServer(
        name="jren-campus-assistant",
        title="J人校园助手",
        description=(
            "校园日程与复习助手：生成 / 预览 / 确认 / 调整每日计划，"
            "查询课程、作业任务与复习计划，标记完成并校准耗时预估。"
        ),
        version=settings.app_version,
        log_level="WARNING",
    )

    # ---------- 计划：生成 / 预览 / 确认 / 调整 / 完成 ----------

    @server.tool(name="generate_tomorrow_plan", description=_TOOL_DESCRIPTIONS["generate_tomorrow_plan"])
    @safe
    def generate_tomorrow_plan(date: str | None = None) -> str:
        plan_date = parse_date(date) if date else tomorrow()
        with session_scope() as db:
            result = generate_plan(db, plan_date)
        return json.dumps(
            {
                "date": plan_date.isoformat(),
                "placed": result.placed_count,
                "dropped": result.dropped,
                "skipped": result.skipped,
                "message": f"已生成 {plan_date.isoformat()} 计划草案（{result.placed_count} 项）"
                + ("；有放不下的项目，可手动调整" if result.dropped else ""),
            },
            ensure_ascii=False,
        )

    @server.tool(name="get_today_plan_preview", description=_TOOL_DESCRIPTIONS["get_today_plan_preview"])
    @safe
    def get_today_plan_preview(date: str | None = None) -> str:
        plan_date = parse_date(date) if date else shanghai_today()
        with session_scope() as db:
            return preview_plan_text(db, plan_date)

    @server.tool(name="confirm_plan", description=_TOOL_DESCRIPTIONS["confirm_plan"])
    @safe
    def confirm_plan_tool(date: str) -> str:
        plan_date = parse_date(date)
        notion_error: str | None = None
        with session_scope() as db:
            writer = None
            try:
                writer = build_writer(db)
            except NotionCalendarError as exc:
                notion_error = str(exc)
            result = confirm_plan(db, plan_date, calendar_writer=writer)
        payload: dict[str, Any] = {
            "date": plan_date.isoformat(),
            "confirmed_count": result.confirmed_count,
            "version": result.version,
            "notion_sync": result.notion_sync,
        }
        if notion_error and payload["notion_sync"] is None:
            payload["notion_sync"] = {"error": notion_error}
        if payload["notion_sync"] and "error" in payload["notion_sync"]:
            payload["message"] = (
                f"已确认 {result.confirmed_count} 项（v{result.version}），"
                f"但 Notion 日历写入失败：{payload['notion_sync']['error']}"
            )
        else:
            payload["message"] = (
                f"已确认 {result.confirmed_count} 项"
                + (f"（v{result.version}）" if result.version else "")
                + (f"，Notion 日历同步：新建 {payload['notion_sync']['created']} / "
                   f"更新 {payload['notion_sync']['updated']} / 不变 {payload['notion_sync']['unchanged']}"
                   if payload["notion_sync"] else "（未配置 Notion 数据源，跳过日历同步）")
            )
        return json.dumps(payload, ensure_ascii=False)

    @server.tool(name="adjust_plan_item", description=_TOOL_DESCRIPTIONS["adjust_plan_item"])
    @safe
    def adjust_plan_item_tool(
        item_id: int, start_time: str, end_time: str, title: str | None = None
    ) -> str:
        with session_scope() as db:
            item = adjust_plan_item(db, item_id, start_time, end_time, title)
        return json.dumps(item, ensure_ascii=False)

    @server.tool(name="mark_done", description=_TOOL_DESCRIPTIONS["mark_done"])
    @safe
    def mark_done_tool(item_id: int, actual_minutes: int | None = None) -> str:
        with session_scope() as db:
            result = mark_done(db, item_id, actual_minutes)
        return json.dumps(result, ensure_ascii=False)

    # ---------- 查询 ----------

    @server.tool(name="get_courses", description=_TOOL_DESCRIPTIONS["get_courses"])
    @safe
    def get_courses_tool() -> str:
        with session_scope() as db:
            return json.dumps(list_courses(db), ensure_ascii=False)

    @server.tool(name="get_tasks", description=_TOOL_DESCRIPTIONS["get_tasks"])
    @safe
    def get_tasks_tool(status: str | None = None) -> str:
        with session_scope() as db:
            return json.dumps(list_tasks(db, status=status), ensure_ascii=False)

    @server.tool(name="get_reviews", description=_TOOL_DESCRIPTIONS["get_reviews"])
    @safe
    def get_reviews_tool(due_date: str | None = None) -> str:
        with session_scope() as db:
            return json.dumps(list_reviews(db, due_date=due_date), ensure_ascii=False)

    return server
