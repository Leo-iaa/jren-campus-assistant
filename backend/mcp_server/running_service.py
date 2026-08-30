"""跑步训练计划编排：COROS 数据 → 规则引擎 → 训练块进日程。

把 ``backend/mcp_client/coros.py``（数据接入）与
``backend/scheduler/running_plan.py``（纯规则引擎）组装成 MCP 工具能力：
- get_running_data：拉取跑步数据快照（实时查询，不落库）
- generate_running_plan：生成未来一周训练计划，并按需以「杂项 misc」
  身份逐日插入日程（复用 _find_free_slot 冲突检查；训练块作为运动
  不受晚间脑力截止限制；该日已确认计划保持 confirmed 并同步 Notion 日历）

跑步时间偏好（Issue #65）：训练块排进日程时尊重用户画像——画像
fixed_activities 有跑步习惯时段时以该时段为锚（经由 misc 的
preferred_time 机制）；无画像时贪心最早适配，用户可再手动调整。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from backend.mcp_client.coros import (
    CorosAdapter,
    CorosAuthError,
    CorosError,
    RunningSnapshot,
)
from backend.mcp_client.service import SyncAuthError, _load_config
from backend.mcp_server.service import _day_locked, parse_date, shanghai_today
from backend.models import DataSource, PlanItem
from backend.scheduler.running_plan import (
    WeekPlan,
    generate_week_plan,
)


class RunningPlanError(Exception):
    """跑步计划生成失败（数据源缺失 / 查询失败等）。"""


@dataclass(frozen=True)
class ScheduleResult:
    """训练块写入日程的结果。"""

    placed: list[dict]  # [{date, start_time, end_time, title, status}]
    failed: list[str]  # 放不下的日期与原因


def _load_coros_source(db: Session, source_id: int | None = None) -> tuple[DataSource, dict]:
    """找到 coros 数据源（缺省取唯一一个启用的），返回 (source, config)。"""
    query = db.query(DataSource).filter(DataSource.source_type == "coros")
    if source_id is not None:
        source = db.get(DataSource, source_id)
        if source is None or source.source_type != "coros":
            raise RunningPlanError(f"coros 数据源不存在（id={source_id}）")
    else:
        source = query.order_by(DataSource.id).first()
    if source is None:
        raise RunningPlanError(
            "尚未绑定 COROS 数据源：请先在数据源管理里绑定 coros 并完成授权"
        )
    config = _load_config(source)
    tokens = config.get("tokens") or {}
    if not tokens.get("access_token"):
        raise SyncAuthError(
            "COROS 未授权：请先通过 POST /api/data-sources/coros/oauth/start 完成登录授权"
        )
    return source, config


def _build_adapter(db: Session, source_id: int | None = None) -> tuple[CorosAdapter, DataSource, dict]:
    source, config = _load_coros_source(db, source_id)
    tokens = config.get("tokens") or {}
    return CorosAdapter(config, access_token=tokens.get("access_token")), source, config


def get_running_data(
    db: Session,
    *,
    days: int = 7,
    source_id: int | None = None,
) -> dict:
    """拉取近期跑步数据快照（实时查询 COROS，不落库）。"""
    days = min(max(int(days), 1), 90)
    adapter, source, _config = _build_adapter(db, source_id)
    try:
        snapshot = adapter.fetch_running_snapshot(days=days)
    except CorosError as exc:
        raise RunningPlanError(f"COROS 数据查询失败：{exc}") from exc
    finally:
        adapter.close()
    return _snapshot_to_dict(snapshot, days=days)


def _snapshot_to_dict(snapshot: RunningSnapshot, *, days: int) -> dict:
    return {
        "days": days,
        "activities": [
            {
                "date": a.date,
                "distance_km": a.distance_km,
                "duration_minutes": a.duration_minutes,
                "pace_sec_per_km": a.pace_sec_per_km,
                "avg_heart_rate": a.avg_heart_rate,
                "workout_type": a.workout_type,
            }
            for a in snapshot.activities
        ],
        "recovery": snapshot.recovery,
        "fitness": snapshot.fitness,
        "load": snapshot.load,
        "available_tools": snapshot.available_tools,
        "warnings": snapshot.warnings,
    }


def _weekday_cn(d: date) -> str:
    return "一二三四五六日"[d.weekday()]


def _next_monday(today: date) -> date:
    """下一个周一（今天周一则排下周）。"""
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def generate_running_plan(
    db: Session,
    *,
    source_id: int | None = None,
    schedule: bool = False,
    start_date: str | None = None,
    calendar_writer=None,
) -> dict:
    """生成未来一周训练计划（引用真实数据），可选排进日程。

    ``schedule=True`` 时把训练块以杂项 misc 身份逐日插入（增量、
    不动已有安排；放不下进 failed 报告，不产生冲突）。
    """
    adapter, source, _config = _build_adapter(db, source_id)
    try:
        snapshot = adapter.fetch_running_snapshot(days=28)
    except CorosError as exc:
        raise RunningPlanError(f"COROS 数据查询失败：{exc}") from exc
    finally:
        adapter.close()

    plan = generate_week_plan(snapshot)

    result: dict = {
        "week_start": None,
        "weekly_distance_km": plan.weekly_distance_km,
        "sessions": [
            {
                "day_offset": s.day_offset,
                "kind": s.kind,
                "kind_label": s.kind_label,
                "minutes": s.minutes,
                "title": s.title,
                "detail": s.detail,
            }
            for s in plan.sessions
        ],
        "rationale": plan.rationale,
        "warnings": plan.warnings,
        "scheduled": [],
        "failed": [],
    }

    if not schedule:
        result["message"] = (
            f"已生成周训练计划（目标 {plan.weekly_distance_km}km，{len(plan.sessions)} 次训练）；"
            "回复「把跑步计划排进日程」即可写入日程"
        )
        return result

    # 训练块排进日程：从 start_date（缺省下一个周一）起逐日安插
    today = shanghai_today()
    week_start = parse_date(start_date) if start_date else _next_monday(today)
    result["week_start"] = week_start.isoformat()

    for s in plan.sessions:
        day = week_start + timedelta(days=s.day_offset)
        title = f"🏃 {s.title}（约{s.minutes}分钟）"
        placed = _insert_training_block(
            db, day, s.minutes, title, preferred_bucket=None
        )
        if placed is None:
            result["failed"].append(
                f"{day.isoformat()} 周{_weekday_cn(day)}「{s.title}」：当天找不到 {s.minutes} 分钟空闲时段"
            )
            continue
        result["scheduled"].append(
            {
                "item_id": placed.id,
                "date": placed.date,
                "start_time": placed.start_time,
                "end_time": placed.end_time,
                "title": placed.title,
                "status": placed.status,
            }
        )

    # 涉及日已确认（已写日历）→ 增量同步 Notion 日历（尽力而为）
    if calendar_writer is not None:
        touched = sorted(
            {parse_date(it["date"]) for it in result["scheduled"]}
        )
        for d in touched:
            if _day_locked(db, d):
                try:
                    sync = calendar_writer.sync_plan_to_calendar(db, d)
                    result.setdefault("notion_sync", []).append(
                        {
                            "date": d.isoformat(),
                            "created": sync.created,
                            "updated": sync.updated,
                            "unchanged": sync.unchanged,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 —— 日历同步尽力而为
                    result.setdefault("notion_sync", []).append(
                        {"date": d.isoformat(), "error": str(exc)}
                    )

    if result["scheduled"]:
        result["message"] = (
            f"已把 {len(result['scheduled'])} 个训练块排进日程"
            + (f"（{len(result['failed'])} 个没排下）" if result["failed"] else "")
            + "；训练块是杂项性质，可回复「把 XX 挪到 HH:MM」调整"
        )
    else:
        result["message"] = "训练块没能排进日程（时段都被占用），可先调整当日安排再试"
    return result


def _insert_training_block(
    db: Session,
    day: date,
    minutes: int,
    title: str,
    *,
    preferred_bucket: str | None = None,
) -> PlanItem | None:
    """把训练块以杂项身份插入某天日程（增量，不动已有安排）。

    复用 add_task 的空闲时段搜索（8:00-22:00 贪心最早适配）；状态跟随
    当日（已确认日 → confirmed，否则 draft）。跑步是运动，规划器对
    misc 不施加晚间脑力截止限制。
    """
    from backend.mcp_server.service import _find_free_slot  # 局部导入避免循环

    slot = _find_free_slot(db, day, minutes)
    if slot is None:
        return None
    start, end = slot
    item = PlanItem(
        date=day.isoformat(),
        start_time=start.strftime("%H:%M"),
        end_time=end.strftime("%H:%M"),
        item_type="misc",
        ref_id=None,
        title=title,
        status="confirmed" if _day_locked(db, day) else "draft",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
