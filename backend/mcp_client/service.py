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
from backend.mcp_client.coros import (
    DEFAULT_CLIENT_NAME,
    DEFAULT_ISSUER,
    DEFAULT_REDIRECT_URI,
    CorosAdapter,
    CorosAuthError,
    CorosError,
    CorosOAuthConfig,
    refresh_token,
)
from backend.mcp_client.models import CourseSessionItem, NoteItem, SyncResult, TaskItem
from backend.mcp_client.notion import NotionAdapter
from backend.mcp_client.notion_rest import NotionRestError
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


def _normalize_deadline(value: str | None) -> str | None:
    """Notion 日期可能带时刻（ISO 时间串），落库统一为 'YYYY-MM-DD'。

    否则与 tasks.deadline 的 DATE_PATTERN 约定不一致，前端「今天到期」的精确匹配会失效。
    """
    if not value:
        return None
    return value[:10] if len(value) >= 10 else value


def build_oauth_client(config: dict, http: httpx.Client | None = None) -> OAuthClient:
    client_id = config.get("client_id") or os.environ.get("JREN_NOTION_CLIENT_ID", "")
    if not client_id:
        raise SyncError("缺少 Notion client_id：请配置 JREN_NOTION_CLIENT_ID 环境变量或数据源 config.client_id")
    return OAuthClient(
        OAuthConfig(
            client_id=client_id,
            client_secret=config.get("client_secret") or os.environ.get("JREN_NOTION_CLIENT_SECRET"),
            redirect_uri=config.get("redirect_uri")
            or os.environ.get("JREN_NOTION_REDIRECT_URI", "http://localhost:5173/#/oauth/notion/callback"),
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
    if source.source_type == "coros":
        tokens = config.get("tokens") or {}
        return CorosAdapter(config, access_token=tokens.get("access_token"))
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
                    starts_on=item.starts_on,
                    ends_on=item.ends_on,
                )
            )
            created += 1
        else:
            if mode == "overwrite":
                session.end_time = item.end_time
                session.location = item.location
                session.starts_on = item.starts_on
                session.ends_on = item.ends_on
                updated += 1
            else:
                changed = False
                if session.end_time is None and item.end_time:
                    session.end_time = item.end_time
                    changed = True
                if session.location is None and item.location:
                    session.location = item.location
                    changed = True
                # 周次区间：仅在尚未设置时补填（不覆盖手改 / 已导入的区间）
                if session.starts_on is None and item.starts_on:
                    session.starts_on = item.starts_on
                    changed = True
                if session.ends_on is None and item.ends_on:
                    session.ends_on = item.ends_on
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
    except NotionRestError as exc:
        raise SyncError(f"Notion API 调用失败：{exc}") from exc
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
                    deadline=_normalize_deadline(item.deadline),
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
                task.deadline = _normalize_deadline(item.deadline)
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


def build_coros_oauth(config: dict | None = None) -> CorosOAuthConfig:
    """按数据源 config 构造 COROS OAuth 配置（端点可覆盖，缺省官方网关）。"""
    cfg = config if config is not None else {}
    return CorosOAuthConfig(
        issuer=cfg.get("issuer", DEFAULT_ISSUER),
        client_name=cfg.get("client_name", DEFAULT_CLIENT_NAME),
        redirect_uri=cfg.get("redirect_uri", DEFAULT_REDIRECT_URI),
    )


def _sync_coros(db, source: DataSource) -> SyncResult:
    """COROS 同步：查询型数据源，不落库（COROS 服务器有完整历史）。

    校验 token 可用性（过期前自动 refresh 并写回 config）+ 拉一次近 7 天
    跑步快照确认链路连通；数据由训练计划工具实时查询。
    """
    config = _load_config(source)
    tokens = config.get("tokens") or {}
    if not tokens.get("access_token"):
        raise SyncAuthError(
            "COROS 未授权：请先通过 POST /api/data-sources/coros/oauth/start 完成登录授权"
        )

    # token 过期 → 尝试 refresh（成功后把新 token 写回 config）
    try:
        expires_at = float(tokens["expires_at"]) if tokens.get("expires_at") else None
    except (TypeError, ValueError):
        expires_at = None
    if expires_at is not None and expires_at < time.time() + 60:
        refresh = tokens.get("refresh_token")
        client_id = tokens.get("client_id")
        if not refresh or not client_id:
            raise SyncAuthError("COROS token 已过期且无 refresh_token / client_id，请重新授权")
        try:
            fresh = refresh_token(build_coros_oauth(config), client_id, refresh)
        except (CorosError, httpx.HTTPError) as exc:
            raise SyncError(f"COROS token 刷新失败：{exc}") from exc
        fresh["client_id"] = client_id
        config["tokens"] = fresh
        _save_config(source, config)
        tokens = fresh

    adapter = CorosAdapter(config, access_token=tokens.get("access_token"))
    try:
        snapshot = adapter.fetch_running_snapshot(days=7)
    except CorosError as exc:
        raise SyncError(f"COROS 数据查询失败：{exc}") from exc
    finally:
        adapter.close()

    return SyncResult(
        source_id=source.id,
        source_type="coros",
        synced_at=_now_iso(),
        fetched=len(snapshot.activities),
        warnings=snapshot.warnings,
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
    elif source.source_type == "coros":
        result = _sync_coros(db, source)
    else:
        raise SyncError(f"暂不支持同步的数据源类型：{source.source_type}")
    source.last_sync_at = _now_iso()
    return result
