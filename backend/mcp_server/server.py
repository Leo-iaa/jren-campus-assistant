"""MCP Server 暴露层：把后端能力包装为 MCP 工具（WorkBuddy 等客户端可调用）。

- 传输：Streamable HTTP，挂载 ``/mcp`` 路径（接线见 ``backend/main.py``）
- 工具（11 个，对齐 docs/mcp-server.md）：
  generate_tomorrow_plan / get_today_plan_preview / confirm_plan /
  adjust_plan_item / add_task / get_courses / get_tasks / get_reviews / mark_done /
  get_user_profile / update_user_profile
- 每个工具调用使用独立数据库会话（``SessionLocal``），互不干扰；
  ``db_factory`` 可注入（测试指向临时数据库）
- 工具返回 JSON 文本（ensure_ascii=False），便于 LLM 客户端直接阅读；
  出错返回 ``{"error": "..."}``，不让异常透出到协议层

实现约定：业务逻辑全部在 ``backend/mcp_server/service.py``（编排）与
``backend/mcp_server/profile_store.py``（用户画像），
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
from backend.mcp_server.notion_task import NotionTaskError, build_task_writer
from backend.mcp_server.profile_store import get_profile, save_manual_prefs
from backend.mcp_server.service import (
    add_task,
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

#: 工具说明（WorkBuddy 等客户端据此理解用法）
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "generate_tomorrow_plan": (
            "生成次日计划草案（默认明日，可指定日期 YYYY-MM-DD）。"
            "返回：date / placed（放置项数）/ dropped（放不下的项目）/ skipped（跳过的项目）/ "
            "preview（完整计划文本，含每项时间与确认状态，可直接推微信）。"
            "auto_confirm=true 时生成后立即确认并写入 Notion 日历（免睡前确认，"
            "返回 confirm 字段：confirmed_count / version / notion_sync）。"
        ),
    "get_today_plan_preview": (
        "获取今日计划文本（默认今天，可指定日期），适合直接推送微信。"
        "包含课程 / 作业 / 复习 / 杂项时间轴与确认状态。"
        "本地无计划时自动回退读取 Notion 日历当天事件（与用户日历所见一致）。"
    ),
    "confirm_plan": (
        "确认某日计划（YYYY-MM-DD，必填）：draft/adjusted 项转为 confirmed，"
        "写入版本快照，并同步写入 Notion 日历（时段块事件；08:00 提醒由微信推送承担）。"
    ),
    "adjust_plan_item": (
        "调整单个计划项：item_id + 新 start_time/end_time（HH:MM），可选新 title。"
        "与同日其他项时间冲突会报错。若该日计划已确认，自动同步更新 Notion 日历"
        "（返回 notion_sync 与 message）。"
    ),
    "get_courses": "查询课程列表（含 S/A/B/C 档位）。",
    "get_tasks": "查询作业任务列表，可按 status 过滤（todo/doing/done/cancelled）。",
    "get_reviews": "查询复习计划列表，可按 due_date（YYYY-MM-DD）过滤。",
    "add_task": (
        "添加任务（微信一句话加任务）：title 必填，due_date 可选（YYYY-MM-DD），"
        "task_type 可选（作业/实验/考试/其他），course_id 可选，estimated_minutes 可选（分钟）。"
        "自动写入本地任务库与 Notion 任务库；无确认概念——无 ddl 或 ddl 是今天/明天的任务"
        "直接增量插入对应日期的空闲时段（不动已有安排）并同步 Notion 日历；"
        "ddl 更远则下次 21:00 生成时纳入。返回：task / plan_message / notion_sync。"
    ),
    "mark_done": (
        "标记计划项完成：item_id 必填，actual_minutes 为实际耗时（分钟，可选）。"
        "task/review 项记录「预估 vs 实际」校准；review 项联动复习计划置 done。"
    ),
    "get_user_profile": (
        "查询用户画像：手动偏好（rhythm 作息：早鸟/夜猫/普通；no_brain_after："
        "晚间脑力截止 HH:MM；fixed_activities：固定生活安排列表）+ 自动学习到的特征"
        "（prefer_bucket 调整偏好 / fit_bucket 完成时段 / late_worker 夜猫线索，"
        "每条含 confidence 观察次数与 evidence 中文证据，可回答「为什么这么排」）"
        "+ 最近行为事件。"
    ),
    "update_user_profile": (
        "手动调整用户画像：rhythm（早鸟/夜猫/普通）、no_brain_after（HH:MM，"
        "晚上几点后不排脑力任务）、fixed_activities（JSON 数组字符串，如 "
        '[{"title":"跑步","days":"一三五","start":"17:00","end":"18:00"}]，'
        "days 可为「每天」或「一二三四五六日」子集）。"
        "传空字符串 \"\" 表示清除该设置；不传表示不修改。返回更新后的完整画像。"
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
            "查询课程、作业任务与复习计划，标记完成并校准耗时预估，"
            "维护用户画像（手动偏好 + 从行为自动学习）。"
        ),
        version=settings.app_version,
        log_level="WARNING",
    )

    # ---------- 计划：生成 / 预览 / 确认 / 调整 / 完成 ----------

    @server.tool(name="generate_tomorrow_plan", description=_TOOL_DESCRIPTIONS["generate_tomorrow_plan"])
    @safe
    def generate_tomorrow_plan(date: str | None = None, auto_confirm: bool = False) -> str:
        plan_date = parse_date(date) if date else tomorrow()
        confirm_payload: dict[str, Any] | None = None
        with session_scope() as db:
            result = generate_plan(db, plan_date)
            preview = preview_plan_text(db, plan_date)
            if auto_confirm:
                # 免确认直达日历：生成后立即确认（draft→confirmed + 版本快照 + 写 Notion 日历）
                notion_error: str | None = None
                writer = None
                try:
                    writer = build_writer(db)
                except NotionCalendarError as exc:
                    notion_error = str(exc)
                confirmed = confirm_plan(db, plan_date, calendar_writer=writer)
                confirm_payload = {
                    "confirmed_count": confirmed.confirmed_count,
                    "version": confirmed.version,
                    "notion_sync": confirmed.notion_sync,
                }
                if notion_error and confirm_payload["notion_sync"] is None:
                    confirm_payload["notion_sync"] = {"error": notion_error}
        payload: dict[str, Any] = {
            "date": plan_date.isoformat(),
            "placed": result.placed_count,
            "dropped": result.dropped,
            "skipped": result.skipped,
            "preview": preview,
        }
        if auto_confirm:
            payload["confirm"] = confirm_payload
            confirmed_count = confirm_payload["confirmed_count"]
            if confirmed_count > 0:
                payload["message"] = (
                    f"已生成并自动确认 {plan_date.isoformat()} 计划（{confirmed_count} 项），"
                    "已写入 Notion 日历，无需再手动确认"
                )
            else:
                payload["message"] = f"{plan_date.isoformat()} 计划已是确认状态，未重复处理"
        else:
            payload["message"] = (
                f"已生成 {plan_date.isoformat()} 计划草案（{result.placed_count} 项）"
                + ("；有放不下的项目，可手动调整" if result.dropped else "")
            )
        return json.dumps(payload, ensure_ascii=False)

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
        notion_error: str | None = None
        writer = None
        with session_scope() as db:
            try:
                writer = build_writer(db)
            except NotionCalendarError as exc:
                notion_error = str(exc)
            item = adjust_plan_item(
                db, item_id, start_time, end_time, title, calendar_writer=writer
            )
        if notion_error and item.get("notion_sync") is None and "notion_sync" in item:
            item["notion_sync"] = {"error": notion_error}
        sync = item.get("notion_sync")
        if sync is None:
            item["message"] = f"已调整「{item['title']}」为 {item['start_time']}-{item['end_time']}"
        elif "error" in sync:
            item["message"] = (
                f"已调整「{item['title']}」为 {item['start_time']}-{item['end_time']}"
                f"（Notion 日历同步失败：{sync['error']}）"
            )
        else:
            item["message"] = (
                f"已调整「{item['title']}」为 {item['start_time']}-{item['end_time']}"
                f"（Notion 日历同步：新建 {sync['created']} / 更新 {sync['updated']} / 不变 {sync['unchanged']}）"
            )
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

    @server.tool(name="add_task", description=_TOOL_DESCRIPTIONS["add_task"])
    @safe
    def add_task_tool(
        title: str,
        due_date: str | None = None,
        task_type: str | None = None,
        course_id: int | None = None,
        estimated_minutes: int | None = None,
    ) -> str:
        notion_error: str | None = None
        task_writer = None
        calendar_writer = None
        with session_scope() as db:
            try:
                task_writer = build_task_writer(db)
            except NotionTaskError as exc:
                notion_error = str(exc)
            try:
                calendar_writer = build_writer(db)  # 排入日程后同步 Notion 日历
            except NotionCalendarError as exc:
                notion_error = notion_error or str(exc)
            result = add_task(
                db,
                title=title,
                due_date=due_date,
                task_type=task_type,
                course_id=course_id,
                estimated_minutes=estimated_minutes,
                task_writer=task_writer,
                calendar_writer=calendar_writer,
            )
        payload: dict[str, Any] = {
            "task": result.task,
            "plan_action": result.plan_action,
            "plan_message": result.plan_message,
            "placed": result.placed,
            "evicted": result.evicted,
            "notion_sync": result.notion_sync,
        }
        if notion_error and payload["notion_sync"] is None:
            payload["notion_sync"] = {"error": notion_error}
        message = f"已添加任务「{result.task['title']}」；{result.plan_message}"
        sync = payload["notion_sync"]
        if sync and "error" in sync:
            message += f"（Notion 任务库写入失败：{sync['error']}）"
        elif sync and sync.get("missing_props"):
            message += (
                "（Notion 任务库缺少属性："
                + "、".join(sync["missing_props"])
                + "，已跳过；在 Notion 补上后自动生效）"
            )
        payload["message"] = message
        return json.dumps(payload, ensure_ascii=False)

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

    # ---------- 用户画像 ----------

    @server.tool(name="get_user_profile", description=_TOOL_DESCRIPTIONS["get_user_profile"])
    @safe
    def get_user_profile_tool() -> str:
        with session_scope() as db:
            return json.dumps(get_profile(db), ensure_ascii=False)

    @server.tool(
        name="update_user_profile", description=_TOOL_DESCRIPTIONS["update_user_profile"]
    )
    @safe
    def update_user_profile_tool(
        rhythm: str | None = None,
        no_brain_after: str | None = None,
        fixed_activities: str | None = None,
    ) -> str:
        with session_scope() as db:
            return json.dumps(
                save_manual_prefs(
                    db,
                    rhythm=rhythm,
                    no_brain_after=no_brain_after,
                    fixed_activities=fixed_activities,
                ),
                ensure_ascii=False,
            )

    return server
