"""数据源同步服务：adapter 结果 → 业务表落库 + 同步状态管理。

- iCal → courses + course_sessions：
  merge（默认）只补空缺字段，不覆盖手改（手动维护兜底）；
  overwrite 全量覆盖 iCal 相关字段（仍不删除任何行，删除走手动 CRUD）
- Notion → tasks（按 source_ref 幂等 upsert，source='notion'，token 过期自动刷新）
- Obsidian → 仅查询接口，不落库（知识点提取归知识提取模块）

同步成功后统一更新 data_sources.last_sync_at。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from backend.models import Course, CourseSession, DataSource, Task
from backend.mcp_client.ical import IcalAdapter
from backend.mcp_client.models import CourseSessionItem, NoteItem, SyncResult, TaskItem
from backend.mcp_client.notion import NotionAdapter
from backend.mcp_client.oauth import DEFAULT_AUTH_URL, DEFAULT_TOKEN_URL, OAuthClient, OAuthConfig, OAuthToken
from backend.mcp_client.obsidian import ObsidianAdapter
from backend.mcp_client.transport import JsonRpcError

_SHANGHAI = ZoneInfo("Asia/Shanghai")


class SyncError(Exception):
    """同步失败（参数缺失 / 传输错误等，API 层映射为 4xx/5xx）。"""


class SyncAuthError(SyncError):
    """授权缺失或失效（API 层映射为 401）。"""


def _now_iso() -> str:
    return datetime.now(_SHANGHAI).isoformat(timespec="seconds")


def _load_config(source: DataSource) -> dict:
    if not source.config:
        return {}
    try:
        data = json.loads(source.config)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _save_config(source: DataSource, config: dict) -> None:
    source.config = json.dumps(config, ensure_ascii=False)


def _token_dict(token: OAuthToken) -> dict:
    return {
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "expires_at": token.expires_at,
    }


def build_oauth_client(config: dict, http: httpx.Client | None = None) -> OAuthClient:
    """按 config / 环境变量构造 OAuth 客户端（client_id 必须可解析）。"""
    client_id = config.get("client_id") or os.environ.get("JREN_NOTION_CLIENT_ID", "")
    if not client_id:
        raise SyncError("缺少 Notion client_id：请配置 JREN_NOTION_CLIENT_ID 环境变量或数据源 config.client_id")
    return OAuthClient(
        OAuthConfig(
            client_id=client_id,
            client_secret=config.get("client_secret") or os.environ.get("JREN_NOTION_CLIENT_SECRET"),
            redirect_uri=config.get("redirect_uri")
            or os.environ.get("JREN_NOTION_REDIRECT_URI", "http://localhost:5173/oauth/notion/callback"),
            auth_url=config.get("auth_url", DEFAULT_AUTH_URL),
            token_url=config.get("token_url", DEFAULT_TOKEN_URL),
        ),
        http=http,
    )


def build_adapter(source: DataSource):
    """按数据源类型构建对应 adapter（真实接入时使用）。"""
    config = _load_config(source)
    if source.source_type == "ical":
        return IcalAdapter(ics_path=config.get("ics_path"))
    if source.source_type == "notion":
        tokens = config.get("tokens") or {}
        return NotionAdapter(config, access_token=tokens.get("access_token"))
    if source.source_type == "obsidian":
        return ObsidianAdapter(config)
    raise SyncError(f"不支持的数据源类型：{source.source_type}")


def _match_course(db, course_name: str | None) -> Course | None:
    if not course_name:
        return None
    return db.query(Course).filter(Course.name == course_name).first()


# ---------- 各类型同步 ----------


def _sync_ical(db, source: DataSource, ics_content: str | None = None, mode: str = "merge") -> SyncResult:
    config = _load_config(source)
    ics_path = config.get("ics_path")
    if ics_path is None and ics_content is None:
        raise SyncError("iCal 数据源缺少同步源：请配置 config.ics_path 或提交 ics_content")
    try:
        adapter = IcalAdapter(ics_path=ics_path, ics_content=ics_content)
        items, warnings = adapter.parse()
    except ValueError as exc:
        raise SyncError(str(exc)) from exc

    created = updated = skipped = 0
    for item in items:
        course = db.query(Course).filter(Course.name == item.course_name).first()
        if course is None:
            course = Course(name=item.course_name, teacher=item.teacher, code=item.course_code)
            db.add(course)
            db.flush()
            created += 1
        else:
            if mode == "overwrite":
                if item.teacher:
                    course.teacher = item.teacher
                if item.course_code:
                    course.code = item.course_code
                updated += 1
            else:
                if course.teacher is None and item.teacher:
                    course.teacher = item.teacher
                if course.code is None and item.course_code:
                    course.code = item.course_code

        session = (
            db.query(CourseSession)
            .filter(
                CourseSession.course_id == course.id,
                CourseSession.day_of_week == item.day_of_week,
                CourseSession.start_time == item.start_time,
            )
            .first()
        )
        if session is None:
            db.add(
                CourseSession(
                    course_id=course.id,
                    day_of_week=item.day_of_week,
                    start_time=item.start_time,
                    end_time=item.end_time,
                    location=item.location,
                    release_slot=0,
                )
            )
            created += 1
        else:
            if mode == "overwrite":
                session.end_time = item.end_time
                session.location = item.location
                updated += 1
            else:
                changed = False
                if session.end_time is None and item.end_time:
                    session.end_time = item.end_time
                    changed = True
                if session.location is None and item.location:
                    session.location = item.location
                    changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1

    return SyncResult(
        source_id=source.id,
        source_type="ical",
        synced_at=_now_iso(),
        fetched=len(items),
        created=created,
        updated=updated,
        skipped=skipped,
        warnings=warnings,
    )


def _sync_notion(db, source: DataSource, database_id: str | None = None, max_pages: int = 50) -> SyncResult:
    config = _load_config(source)
    tokens = config.get("tokens") or {}
    access_token = tokens.get("access_token")
    if not access_token:
        raise SyncAuthError("Notion 未授权：请先通过 POST /api/data-sources/notion/oauth/start 完成授权")

    # token 过期 → 尝试 refresh（成功后把新 token 写回 config）
    try:
        expires_at = float(tokens["expires_at"]) if tokens.get("expires_at") else None
    except (TypeError, ValueError):
        expires_at = None
    if expires_at is not None and expires_at < time.time() + 60:
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise SyncAuthError("Notion token 已过期且无 refresh_token，请重新授权")
        try:
            token = build_oauth_client(config).refresh(refresh_token)
        except httpx.HTTPError as exc:
            raise SyncError(f"Notion token 刷新失败：{exc}") from exc
        config["tokens"] = _token_dict(token)
        _save_config(source, config)
        access_token = token.access_token

    adapter = NotionAdapter(config, access_token=access_token)
    try:
        items = adapter.fetch_tasks(database_id or config.get("database_id"), max_pages=max_pages)
    except ValueError as exc:
        raise SyncError(str(exc)) from exc
    except JsonRpcError as exc:
        raise SyncError(f"Notion MCP 调用失败：{exc}") from exc
    finally:
        adapter.close()

    created = updated = skipped = 0
    for item in items:
        task = (
            db.query(Task)
            .filter(Task.source == "notion", Task.source_ref == item.source_ref)
            .first()
        )
        if task is None:
            course = _match_course(db, item.course_name)
            db.add(
                Task(
                    title=item.title,
                    description=item.description,
                    deadline=item.deadline,
                    course_id=course.id if course else None,
                    source="notion",
                    source_ref=item.source_ref,
                    status=item.status,
                )
            )
            created += 1
        else:
            task.title = item.title
            task.status = item.status
            if item.description is not None:
                task.description = item.description
            if item.deadline is not None:
                task.deadline = item.deadline
            course = _match_course(db, item.course_name)
            task.course_id = course.id if course else task.course_id
            updated += 1

    return SyncResult(
        source_id=source.id,
        source_type="notion",
        synced_at=_now_iso(),
        fetched=len(items),
        created=created,
        updated=updated,
        skipped=skipped,
    )


def _sync_obsidian(db, source: DataSource, query: str | None = None, limit: int = 20) -> SyncResult:
    config = _load_config(source)
    adapter = ObsidianAdapter(config)
    try:
        if query:
            items: list[NoteItem] = adapter.search(query, limit=limit)
        else:
            items = adapter.list_notes(limit=limit)
    except ValueError as exc:
        raise SyncError(str(exc)) from exc
    except JsonRpcError as exc:
        raise SyncError(f"Obsidian MCP 调用失败：{exc}") from exc

    # 只做接入与查询，不落库（知识点提取归知识提取模块）
    return SyncResult(
        source_id=source.id,
        source_type="obsidian",
        synced_at=_now_iso(),
        fetched=len(items),
    )


def sync_data_source(
    db,
    source: DataSource,
    ics_content: str | None = None,
    mode: str = "merge",
    query: str | None = None,
    database_id: str | None = None,
) -> SyncResult:
    """按数据源类型分发同步，成功后更新 last_sync_at。"""
    if source.source_type == "ical":
        result = _sync_ical(db, source, ics_content=ics_content, mode=mode)
    elif source.source_type == "notion":
        result = _sync_notion(db, source, database_id=database_id)
    elif source.source_type == "obsidian":
        result = _sync_obsidian(db, source, query=query)
    else:
        raise SyncError(f"暂不支持同步的数据源类型：{source.source_type}")
    source.last_sync_at = _now_iso()
    return result
