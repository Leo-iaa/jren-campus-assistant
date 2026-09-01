"""计划编排服务：MCP Server 暴露层的业务核心。

把 ``backend/scheduler/`` 的纯算法（规划器 / 校准器）与 ORM 数据组装成
「生成 / 预览 / 确认 / 调整 / 完成 / 查询」能力，供 MCP 工具与 APScheduler
定时任务共用。所有方法接收 ``sqlalchemy.orm.Session``，不感知 FastAPI / MCP。

时间约定：
- 日期一律使用 ``Asia/Shanghai`` 时区（对齐 docs/vision.md 时间轴）
- 数据库时间字段为 'HH:MM' 文本、日期为 'YYYY-MM-DD' 文本（docs/database.md）

生成语义（幂等、不破坏已确认计划）：
- 某日已有 confirmed 计划项时不再自动重排（避免覆盖用户已确认的安排），
  返回 skipped 说明，改动请走 adjust_plan_item
- 其余情况（全部为 draft/adjusted 或混有 done）重新生成：仅替换 status 为
  draft / adjusted 的旧计划项，done 项保留不动
- 与保留项（done）起始时间冲突的新草案跳过并在结果中报告
  （保持 UNIQUE(date, start_time)）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.models import (
    CalibrationStat,
    Course,
    CourseSession,
    KnowledgePoint,
    MiscItem,
    PlanItem,
    PlanVersion,
    ReviewSchedule,
    Setting,
    Task,
)
from backend.mcp_server import profile_store
from backend.scheduler.calibration import TIME_BUCKETS
from backend.scheduler.interfaces import PlanItemDraft
from backend.scheduler.planner import build_plan_full
from backend.scheduler.profile import bucket_of_time, subject_for

_SHANGHAI = ZoneInfo("Asia/Shanghai")

#: 计划项类型的 emoji 与中文名（预览文本用）
ITEM_TYPE_LABELS: dict[str, tuple[str, str]] = {
    "course": ("📚", "课程"),
    "task": ("📝", "作业"),
    "review": ("🔁", "复习"),
    "misc": ("🗓", "杂项"),
}

#: 校准时段分桶（对齐 calibration_stats.time_bucket）
_MORNING_END = time(12, 0)
_AFTERNOON_END = time(18, 0)

#: 默认时长（分钟），可用 settings 表覆盖
DEFAULT_TASK_MINUTES = 60
DEFAULT_REVIEW_MINUTES = 30

#: 单条目时长上限（分钟）：超过视为异常，clamp 以免 time() 溢出（hour>23）崩溃
MAX_DURATION_MINUTES = 720


# ---------- 结果数据结构 ----------


@dataclass(frozen=True)
class GeneratePlanResult:
    """计划生成结果。"""

    plan_date: date
    placed_count: int
    dropped: list[str] = field(default_factory=list)  # 放不下（时间不够）
    skipped: list[str] = field(default_factory=list)  # 缺时长 / 与保留项冲突


@dataclass(frozen=True)
class ConfirmResult:
    """计划确认结果。"""

    plan_date: date
    confirmed_count: int
    version: int | None
    notion_sync: dict | None = None  # Notion Calendar 写入结果或错误信息


# ---------- 工具函数 ----------


def shanghai_today() -> date:
    """上海时区今天。"""
    return datetime.now(_SHANGHAI).date()


def tomorrow() -> date:
    """上海时区明天。"""
    return shanghai_today() + timedelta(days=1)


def parse_date(value: str) -> date:
    """解析 'YYYY-MM-DD'（非法抛 ValueError，中文报错）。"""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"日期格式应为 YYYY-MM-DD，收到: {value!r}") from None


def parse_hhmm(value: str) -> time:
    """解析 'HH:MM'（非法抛 ValueError，中文报错）。"""
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValueError(f"时间格式应为 HH:MM，收到: {value!r}") from None


def _get_setting(db: Session, key: str, default: str) -> str:
    """读取 settings 键值表（不存在返回默认值）。"""
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row is not None else default


def _item_to_dict(item: PlanItem) -> dict:
    """PlanItem → 字典（工具返回 / 快照用）。"""
    return {
        "id": item.id,
        "date": item.date,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "item_type": item.item_type,
        "ref_id": item.ref_id,
        "title": item.title,
        "status": item.status,
    }


def time_bucket_for(start_time: str) -> str:
    """按开始时间映射校准时段分桶（morning/afternoon/evening）。"""
    t = parse_hhmm(start_time)
    if t < _MORNING_END:
        return "morning"
    if t < _AFTERNOON_END:
        return "afternoon"
    return "evening"


# ---------- 生成 ----------


def generate_plan(db: Session, plan_date: date) -> GeneratePlanResult:
    """生成某日建议计划并落库（draft 状态），返回放置 / 放不下 / 跳过明细。"""
    task_minutes = int(_get_setting(db, "task_duration_minutes", str(DEFAULT_TASK_MINUTES)))
    review_minutes = int(_get_setting(db, "review_duration_minutes", str(DEFAULT_REVIEW_MINUTES)))
    if task_minutes <= 0 or review_minutes <= 0:
        raise ValueError("设置 task_duration_minutes / review_duration_minutes 必须为正整数")

    # 1. 固定课程块（当日星期几的课程时间块；B/C 档 release_slot=1 释放给其他任务）
    #    周次区间（starts_on/ends_on）为空表示整学期有效；否则仅保留目标日期落在
    #    生效区间内的课程（支持前后半学期同星期同时段的不同课程错峰，如机械原理Ⅱ/
    #    航空航天材料工程）
    plan_iso = plan_date.isoformat()
    sessions = (
        db.query(CourseSession)
        .join(Course, CourseSession.course_id == Course.id)
        .filter(CourseSession.day_of_week == plan_date.weekday())
        .order_by(CourseSession.start_time)
        .all()
    )
    sessions = [
        s
        for s in sessions
        if (s.starts_on is None or s.starts_on <= plan_iso)
        and (s.ends_on is None or s.ends_on >= plan_iso)
    ]
    course_drafts = [
        PlanItemDraft(
            date=plan_date,
            start=parse_hhmm(s.start_time),
            end=parse_hhmm(s.end_time),
            item_type="course",
            ref_id=s.id,
            title=s.course.name,
            release_slot=bool(s.release_slot),
        )
        for s in sessions
    ]

    # 1.5 用户画像偏好（Issue #63）：偏好时段 / 晚间脑力截止 / 固定安排屏障。
    #     画像为空时全部为空 → 规划行为与旧版完全一致
    prefs = profile_store.load_planner_prefs(db, plan_date)

    # 2. 作业任务（未完成且 deadline 未早于当日；无预估时长用默认值）
    iso = plan_date.isoformat()
    pending_tasks = (
        db.query(Task).filter(Task.status.in_(["todo", "doing"])).order_by(Task.id).all()
    )
    task_drafts: list[PlanItemDraft] = []
    for t in pending_tasks:
        if t.deadline and (t.deadline[:10] < iso):
            continue  # 已过期的任务不自动排（用户另行处理）
        minutes = _clamp_duration(t.estimated_minutes, task_minutes)
        subject = subject_for(t.course.name if t.course else None, t.title)
        task_drafts.append(
            PlanItemDraft(
                date=plan_date,
                start=time(0, 0),  # 占位：规划器只取 end-start 作为时长
                end=_minutes_to_time(minutes),
                item_type="task",
                ref_id=t.id,
                title=t.title,
                preferred_bucket=prefs.preferred_buckets.get(subject),
            )
        )

    # 3. 复习（当日到期且未完成；时长取设置）
    due_reviews = (
        db.query(ReviewSchedule)
        .filter(
            ReviewSchedule.due_date == iso,
            ReviewSchedule.status.in_(["pending", "overdue"]),
        )
        .order_by(ReviewSchedule.id)
        .all()
    )
    review_drafts: list[PlanItemDraft] = []
    for rs in due_reviews:
        kp = db.get(KnowledgePoint, rs.knowledge_point_id)
        title = f"复习 · {kp.title if kp else f'知识点#{rs.knowledge_point_id}'}"
        subject = subject_for(kp.course.name if kp and kp.course else None, title)
        review_drafts.append(
            PlanItemDraft(
                date=plan_date,
                start=time(0, 0),
                end=_minutes_to_time(_clamp_duration(review_minutes, review_minutes)),
                item_type="review",
                ref_id=rs.id,
                title=title,
                preferred_bucket=prefs.preferred_buckets.get(subject),
            )
        )

    # 4. 杂项（未完成；缺时长则跳过并报告）
    misc_drafts: list[PlanItemDraft] = []
    skipped: list[str] = []
    for m in (
        db.query(MiscItem).filter(MiscItem.status == "todo").order_by(MiscItem.id).all()
    ):
        minutes = _clamp_duration(m.duration_minutes, 0)
        if minutes == 0:
            skipped.append(f"杂项「{m.title}」缺少有效时长（duration_minutes），跳过")
            continue
        # 杂项偏好：显式 preferred_time > 画像学习（prefer/fit）> 无偏好
        declared_bucket: str | None = None
        if m.preferred_time:
            try:
                declared_bucket = bucket_of_time(parse_hhmm(m.preferred_time))
            except ValueError:
                declared_bucket = None  # 非法偏好时间忽略
        preferred_bucket = declared_bucket or prefs.preferred_buckets.get(
            subject_for(None, m.title)
        )
        misc_drafts.append(
            PlanItemDraft(
                date=plan_date,
                start=time(0, 0),
                end=_minutes_to_time(minutes),
                item_type="misc",
                ref_id=m.id,
                title=m.title,
                preferred_bucket=preferred_bucket,
            )
        )

    # 5. 学习时段偏好（settings.study_hours，格式 'HH:MM-HH:MM'，非法则忽略）
    study_hours = _parse_study_hours(_get_setting(db, "study_hours", ""))

    # 6. 规划器求解（确定性贪心，保证不冲突 + UNIQUE(start)）；
    #    画像约束：偏好时段 / 晚间脑力截止 / 固定安排屏障（空画像不生效）
    result = build_plan_full(
        plan_date,
        course_drafts,
        task_drafts,
        review_drafts,
        misc_drafts,
        study_hours,
        brain_curfew=prefs.no_brain_after,
        extra_barriers=prefs.barriers or None,
    )
    dropped = [f"{ITEM_TYPE_LABELS[d.item_type][1]}「{d.title}」" for d in result.dropped]

    # 7. 落库：替换 draft/adjusted，保留 done（防冲突占用起始分钟）；
    #    已确认的计划不自动重排（避免覆盖用户安排）
    iso = plan_date.isoformat()
    has_confirmed = (
        db.query(PlanItem.id)
        .filter(PlanItem.date == iso, PlanItem.status == "confirmed")
        .first()
    )
    if has_confirmed is not None:
        return GeneratePlanResult(
            plan_date=plan_date,
            placed_count=0,
            dropped=[],
            skipped=["该日计划已确认，未重新生成（如需调整请使用 adjust_plan_item）"],
        )

    kept = (
        db.query(PlanItem)
        .filter(PlanItem.date == iso, PlanItem.status == "done")
        .all()
    )
    kept_starts = {k.start_time for k in kept}
    for old in (
        db.query(PlanItem)
        .filter(PlanItem.date == iso, PlanItem.status.in_(["draft", "adjusted"]))
        .all()
    ):
        db.delete(old)
    # 先落地删除：SQLAlchemy flush 顺序默认「先插入后删除」，
    # 若新草案与旧 draft 同 start_time，不先 DELETE 会撞 UNIQUE(date, start_time)
    db.flush()

    placed_count = 0
    for draft in result.placed:
        if draft.start.strftime("%H:%M") in kept_starts:
            skipped.append(
                f"{ITEM_TYPE_LABELS[draft.item_type][1]}「{draft.title}」"
                f"与已确认项起始时间冲突，跳过"
            )
            continue
        db.add(
            PlanItem(
                date=iso,
                start_time=draft.start.strftime("%H:%M"),
                end_time=draft.end.strftime("%H:%M"),
                item_type=draft.item_type,
                ref_id=draft.ref_id,
                title=draft.title,
                status="draft",
            )
        )
        placed_count += 1

    db.commit()
    return GeneratePlanResult(
        plan_date=plan_date,
        placed_count=placed_count,
        dropped=dropped,
        skipped=skipped,
    )


def _minutes_to_time(minutes: int) -> time:
    """分钟数 → time（越界抛中文错误，防御来自配置 / 数据的异常时长）。"""
    if minutes < 0 or minutes >= 1440:
        raise ValueError(f"时长超出合理范围（0-1439 分钟）：{minutes}")
    return time(minutes // 60, minutes % 60)


def _clamp_duration(minutes: int | None, default: int) -> int:
    """规范化任务 / 复习时长：缺失或非法用默认值；超大值 clamp 到上限。"""
    if not minutes or minutes <= 0:
        return default
    return min(minutes, MAX_DURATION_MINUTES)


def _parse_study_hours(value: str) -> tuple[time, time] | None:
    """解析 'HH:MM-HH:MM' → (start, end)；空值 / 非法返回 None。"""
    if not value or "-" not in value:
        return None
    start_raw, end_raw = value.split("-", 1)
    try:
        start, end = parse_hhmm(start_raw.strip()), parse_hhmm(end_raw.strip())
    except ValueError:
        return None
    if end <= start:
        return None
    return start, end


# ---------- 预览 ----------


def _preview_from_notion(db: Session, plan_date: date) -> list[str]:
    """本地无计划时，回退读取 Notion 日历当天事件（与用户日历所见一致）。

    未绑定 Notion / 未配置日历库 / 查询失败 → 返回空列表（预览回落"无安排"文案）。
    """
    try:
        from backend.mcp_server.notion_calendar import build_writer

        writer = build_writer(db)
        if writer is None:
            return []
        events = writer.list_events_on(plan_date.isoformat())
        if not events:
            return []
        emoji = {"course": "📚", "task": "📝", "review": "🔁", "misc": "🧘"}
        lines: list[str] = []
        for ev in events:
            start = ev["start"]
            hm = start[11:16] if len(start) >= 16 and start[10] == "T" else start
            icon = emoji.get(ev["type"], "📌")
            lines.append(f"🕗 {hm} {icon} {ev['title']}")
        return lines
    except Exception:
        # 回退路径任何异常都不应影响预览（宁可显示"无安排"）
        return []


def preview_plan_text(db: Session, plan_date: date) -> str:
    """今日/某日计划 → 微信友好文本（供 WorkBuddy 08:00 推送）。"""
    iso = plan_date.isoformat()
    items = (
        db.query(PlanItem)
        .filter(PlanItem.date == iso)
        .order_by(PlanItem.start_time, PlanItem.item_type)
        .all()
    )
    weekday_cn = "一二三四五六日"[plan_date.weekday()]

    lines = [f"📅 今日计划 · {iso} 周{weekday_cn}"]

    if not items:
        lines.append("")
        notion_events = _preview_from_notion(db, plan_date)
        if notion_events:
            lines.append("（本地暂无计划，以下为 Notion 日历中的安排）")
            lines.extend(notion_events)
            lines.append("")
            lines.append("💬 想重新规划这一天？回复「生成明天的计划」。")
            return "\n".join(lines)
        lines.append("今天还没有安排。可以回复「生成明天的计划」，或去网页端手动添加。")
        return "\n".join(lines)

    # 状态行：全部 confirmed/done → 已确认；存在 draft/adjusted → 待确认
    open_items = [it for it in items if it.status in ("draft", "adjusted")]
    if open_items:
        lines.append("⏳ 待确认")
    else:
        version = _latest_version(db, iso)
        lines.append(f"✅ 已确认" + (f" v{version}" if version else ""))

    for item_type in ("course", "task", "review", "misc"):
        group = [it for it in items if it.item_type == item_type]
        if not group:
            continue
        emoji, label = ITEM_TYPE_LABELS[item_type]
        lines.append("")
        lines.append(f"{emoji} {label}（{len(group)}）")
        for it in group:
            location = ""
            if item_type == "course" and it.ref_id:
                session = db.get(CourseSession, it.ref_id)
                if session and session.location:
                    location = f" · {session.location}"
            lines.append(f"🕗 {it.start_time}-{it.end_time} {it.title}{location}")

    lines.append("")
    lines.append("💬 回复「确认今天的计划」；调整可说「把 XXX 挪到 HH:MM」。")
    return "\n".join(lines)


# ---------- 确认 ----------


def confirm_plan(
    db: Session,
    plan_date: date,
    calendar_writer=None,
) -> ConfirmResult:
    """确认某日计划：draft/adjusted → confirmed，并写入 plan_versions 快照。

    ``calendar_writer`` 注入 Notion Calendar 写入器（可 mock）；确认成功后
    尽力同步到日历，失败不阻断确认，结果写入 ``notion_sync`` 字段。
    """
    iso = plan_date.isoformat()
    items = (
        db.query(PlanItem)
        .filter(PlanItem.date == iso, PlanItem.status.in_(["draft", "adjusted"]))
        .order_by(PlanItem.id)
        .all()
    )
    for item in items:
        item.status = "confirmed"

    version = None
    if items:
        version = (_latest_version(db, iso) or 0) + 1
        db.add(
            PlanVersion(
                date=iso,
                version=version,
                payload=json.dumps([_item_to_dict(it) for it in items], ensure_ascii=False),
                confirmed_at=datetime.now(_SHANGHAI).isoformat(timespec="seconds"),
            )
        )
    db.commit()

    notion_sync: dict | None = None
    if calendar_writer is not None:
        try:
            sync_result = calendar_writer.sync_plan_to_calendar(db, plan_date)
            notion_sync = {
                "created": sync_result.created,
                "updated": sync_result.updated,
                "unchanged": sync_result.unchanged,
            }
        except Exception as exc:  # noqa: BLE001 —— 日历写入尽力而为，失败不阻断确认
            notion_sync = {"error": str(exc)}

    return ConfirmResult(
        plan_date=plan_date,
        confirmed_count=len(items),
        version=version,
        notion_sync=notion_sync,
    )


def _latest_version(db: Session, iso: str) -> int | None:
    row = (
        db.query(PlanVersion)
        .filter(PlanVersion.date == iso)
        .order_by(PlanVersion.version.desc())
        .first()
    )
    return row.version if row else None


# ---------- 调整 ----------


def adjust_plan_item(
    db: Session,
    item_id: int,
    start_time: str,
    end_time: str,
    title: str | None = None,
    calendar_writer=None,
) -> dict:
    """调整单个计划项的时间（可选改标题），返回更新后的计划项字典。

    ``calendar_writer`` 注入 Notion Calendar 写入器：**仅当该日计划已确认**
    （即已写入过日历）时增量同步当日到日历（幂等，复用 sync_plan_to_calendar）；
    草案阶段不写日历（确认时统一写入）。同步结果写入返回的 ``notion_sync``
    字段，失败不阻断调整。
    """
    item = db.get(PlanItem, item_id)
    if item is None:
        raise ValueError(f"计划项不存在（id={item_id}）")

    old_start = item.start_time  # 画像学习：记录调整前时段
    new_start = parse_hhmm(start_time)
    new_end = parse_hhmm(end_time)
    if new_end <= new_start:
        raise ValueError(f"结束时间必须晚于开始时间：{start_time} → {end_time}")

    others = (
        db.query(PlanItem)
        .filter(PlanItem.date == item.date, PlanItem.id != item.id)
        .all()
    )
    for other in others:
        o_start, o_end = parse_hhmm(other.start_time), parse_hhmm(other.end_time)
        overlap = new_start < o_end and new_end > o_start
        same_start = new_start == o_start
        if overlap or same_start:
            raise ValueError(
                f"时间冲突：与「{other.title}」({other.start_time}-{other.end_time}) "
                f"重叠或起始时间相同"
            )

    item.start_time = new_start.strftime("%H:%M")
    item.end_time = new_end.strftime("%H:%M")
    item.status = "adjusted"
    if title:
        item.title = title
    db.commit()
    db.refresh(item)
    result = _item_to_dict(item)

    # 用户画像学习（Issue #63）：记录「挪时段」行为并刷新学习特征，
    # 尽力而为——学习失败不影响调整本身
    _learn_from_adjustment(db, item, old_start)

    # 日历同步：仅当该日已有 confirmed 项（确认过并写入过日历）才增量同步
    has_confirmed = (
        db.query(PlanItem.id)
        .filter(PlanItem.date == item.date, PlanItem.status == "confirmed")
        .first()
    )
    if has_confirmed is not None:
        if calendar_writer is not None:
            try:
                sync = calendar_writer.sync_plan_to_calendar(
                    db, parse_date(item.date)
                )
                result["notion_sync"] = {
                    "created": sync.created,
                    "updated": sync.updated,
                    "unchanged": sync.unchanged,
                }
            except Exception as exc:  # noqa: BLE001 —— 日历同步尽力而为
                result["notion_sync"] = {"error": str(exc)}
        else:
            result["notion_sync"] = None  # 未绑定 Notion / 未配置日历库
    return result


# ---------- 完成 + 校准 ----------


def mark_done(db: Session, item_id: int, actual_minutes: int | None = None) -> dict:
    """标记计划项完成：status → done，联动复习计划状态，记录「预估 vs 实际」校准。

    - review 项：同时把关联的 review_schedules 置 done（completed_at 记当前时间）
    - task / review 项且提供 actual_minutes：写入 calibration_stats 分桶统计
    - 重复调用幂等（已 done 直接返回）
    """
    item = db.get(PlanItem, item_id)
    if item is None:
        raise ValueError(f"计划项不存在（id={item_id}）")

    if item.status == "done":
        return _item_to_dict(item)

    item.status = "done"

    linked_review: ReviewSchedule | None = None
    if item.item_type == "review" and item.ref_id:
        linked_review = db.get(ReviewSchedule, item.ref_id)
        if linked_review is not None and linked_review.status != "done":
            linked_review.status = "done"
            linked_review.completed_at = datetime.now(_SHANGHAI).isoformat(timespec="seconds")

    calibration_recorded = False
    if actual_minutes is not None:
        if item.item_type not in ("task", "review"):
            raise ValueError(f"仅 task/review 项参与耗时校准，收到: {item.item_type!r}")
        estimated = _duration_minutes(item)
        _record_calibration(db, item, estimated, actual_minutes)
        calibration_recorded = True

    db.commit()
    result = _item_to_dict(item)
    result["calibration_recorded"] = calibration_recorded
    if linked_review is not None:
        result["linked_review_status"] = linked_review.status

    # 用户画像学习（Issue #63）：记录「完成时段」行为并刷新学习特征，
    # 尽力而为——学习失败不影响完成本身
    _learn_from_completion(db, item)
    return result


def _learn_from_adjustment(db: Session, item: PlanItem, old_start: str) -> None:
    """画像学习：调整行为 → 记录事件 + 刷新学习特征（尽力而为，不抛错）。"""
    try:
        if item.item_type not in ("task", "review", "misc"):
            return  # 课程块是固定安排，不构成偏好信号
        subject, title = profile_store.subject_and_title_for(db, item)
        profile_store.record_event(
            db,
            event_type="adjust",
            plan_date=item.date,
            subject=subject,
            item_type=item.item_type,
            from_bucket=time_bucket_for(old_start),
            to_bucket=time_bucket_for(item.start_time),
            start_time=item.start_time,
            title=title,
        )
        profile_store.refresh_learned_features(db)
        db.commit()
    except Exception:  # noqa: BLE001 —— 画像学习尽力而为
        db.rollback()


def _learn_from_completion(db: Session, item: PlanItem) -> None:
    """画像学习：完成行为 → 记录事件 + 刷新学习特征（尽力而为，不抛错）。"""
    try:
        if item.item_type not in ("task", "review", "misc"):
            return
        subject, title = profile_store.subject_and_title_for(db, item)
        profile_store.record_event(
            db,
            event_type="done",
            plan_date=item.date,
            subject=subject,
            item_type=item.item_type,
            to_bucket=time_bucket_for(item.start_time),
            start_time=item.start_time,
            title=title,
        )
        profile_store.refresh_learned_features(db)
        db.commit()
    except Exception:  # noqa: BLE001 —— 画像学习尽力而为
        db.rollback()


def _duration_minutes(item: PlanItem) -> int:
    return (
        parse_hhmm(item.end_time).hour * 60
        + parse_hhmm(item.end_time).minute
        - (parse_hhmm(item.start_time).hour * 60 + parse_hhmm(item.start_time).minute)
    )


def _record_calibration(
    db: Session, item: PlanItem, estimated_minutes: int, actual_minutes: int
) -> None:
    """按 课程 × 时段 × 难度 × 类型 分桶 upsert calibration_stats。

    factor 始终由 sample_count / ratio_sum 重算（不信任外部传入）。
    """
    if estimated_minutes <= 0:
        raise ValueError(f"预估耗时必须为正：{estimated_minutes}")
    if actual_minutes < 0:
        raise ValueError(f"实际耗时必须 >= 0：{actual_minutes}")

    course_id: int | None = None
    difficulty: int | None = None
    if item.item_type == "review" and item.ref_id:
        rs = db.get(ReviewSchedule, item.ref_id)
        if rs is not None:
            kp = db.get(KnowledgePoint, rs.knowledge_point_id)
            course_id = kp.course_id if kp else None
            difficulty = kp.difficulty if kp else None
    elif item.item_type == "task" and item.ref_id:
        task = db.get(Task, item.ref_id)
        if task is not None:
            course_id = task.course_id

    time_bucket = time_bucket_for(item.start_time)
    if time_bucket not in TIME_BUCKETS:  # 理论不可达，防御性校验
        raise ValueError(f"未知时段分桶: {time_bucket!r}")

    stat = (
        db.query(CalibrationStat)
        .filter(
            CalibrationStat.course_id == course_id,
            CalibrationStat.time_bucket == time_bucket,
            CalibrationStat.difficulty == difficulty,
            CalibrationStat.item_type == item.item_type,
        )
        .first()
    )
    if stat is None:
        stat = CalibrationStat(
            course_id=course_id,
            time_bucket=time_bucket,
            difficulty=difficulty,
            item_type=item.item_type,
            sample_count=0,
            ratio_sum=0.0,
        )
        db.add(stat)
    stat.sample_count += 1
    stat.ratio_sum = round(stat.ratio_sum + actual_minutes / estimated_minutes, 6)
    stat.factor = round(stat.ratio_sum / stat.sample_count, 6)


# ---------- 添加任务 + 计划联动 ----------


#: 任务类型枚举（add_task 校验；与 Notion 任务库「类型」属性对齐）
TASK_TYPES: tuple[str, ...] = ("作业", "实验", "考试", "其他")


@dataclass(frozen=True)
class AddTaskResult:
    """添加任务结果。"""

    task: dict
    notion_sync: dict | None = None  # 任务库写入结果或错误信息
    plan_action: str = "deferred"  # scheduled_today / scheduled_tomorrow / deferred
    plan_message: str = ""  # 计划联动中文说明
    placed: dict | None = None  # 排到目标日的计划项（若有）
    evicted: list[dict] = field(default_factory=list)  # 腾挪顺延的旧计划项（title/从哪天到哪天）


def add_task(
    db: Session,
    *,
    title: str,
    due_date: str | None = None,
    task_type: str | None = None,
    course_id: int | None = None,
    estimated_minutes: int | None = None,
    task_writer=None,
    calendar_writer=None,
) -> AddTaskResult:
    """添加任务：本地落库 → 写 Notion 任务库 → 直接排进日程（无确认概念）。

    - 本地 tasks 表必写（source='manual'，status='todo'）
    - Notion 任务库写入尽力而为：未配置 / 失败不阻断，结果写入 ``notion_sync``
    - 计划联动（设计理由见 docs/mcp-server.md「add_task」）：
      · 无 ddl 或 ddl 是今天 → 直接**增量插入**今天（找空闲时段，不动已有安排，
        即使今天计划已确认；插入后同步 Notion 日历）
      · ddl 是明天 → 直接插入明天（同样不锁）
      · ddl 更远 → 不占位，下次 21:00 生成时自动纳入（每晚生成次日并 auto_confirm）
      · 已过期 → 不自动排，提示手动处理
      ``calendar_writer`` 注入 Notion 日历写入器：插入后若目标日已确认（已写日历）
      则增量同步当日，失败不阻断。
    """
    title = (title or "").strip()
    if not title:
        raise ValueError("任务标题不能为空")

    if due_date is not None:
        parse_date(due_date)  # 校验 YYYY-MM-DD
    if task_type is not None and task_type not in TASK_TYPES:
        raise ValueError(f"未知任务类型: {task_type!r}（应为 {'/'.join(TASK_TYPES)}）")
    if course_id is not None and db.get(Course, course_id) is None:
        raise ValueError(f"所属课程不存在（id={course_id}）")

    # 1. 本地任务落库
    task = Task(
        title=title,
        task_type=task_type,
        deadline=due_date,
        course_id=course_id,
        estimated_minutes=estimated_minutes,
        source="manual",
        status="todo",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 2. Notion 任务库（尽力而为，失败不阻断）
    notion_sync: dict | None = None
    if task_writer is not None:
        try:
            result = task_writer.create_task(
                {
                    "title": task.title,
                    "deadline": task.deadline,
                    "task_type": task.task_type,
                }
            )
            page_id = result.get("page_id")
            if page_id:
                task.source_ref = page_id
                db.commit()
            notion_sync = {
                "created": bool(page_id),
                "page_id": page_id,
                "missing_props": result.get("missing_props", []),
            }
        except Exception as exc:  # noqa: BLE001 —— 任务库写入尽力而为
            notion_sync = {"error": str(exc)}

    # 3. 计划联动（直接插入，无「确认/锁定」概念）
    # 目标日：无 ddl → 今天；ddl 今天 → 今天；ddl 明天 → 明天；
    # 更远 → 不占位（每晚 21:00 生成次日时自动纳入）。插入为增量方式：
    # 找目标日空闲时段安插，不动已排好的其它安排；目标日已写日历则同步 Notion。
    today = shanghai_today()
    iso = today.isoformat()
    task_minutes = _clamp_duration(
        task.estimated_minutes,
        int(_get_setting(db, "task_duration_minutes", str(DEFAULT_TASK_MINUTES))),
    )

    placed_dict: dict | None = None
    evicted: list[dict] = []
    if due_date is not None and due_date < iso:
        plan_action, plan_message = "deferred", "任务截止日期已过，不会自动安排，请手动处理"
    elif due_date is None or due_date <= (today + timedelta(days=1)).isoformat():
        target = parse_date(due_date) if due_date is not None else today
        if target < today:
            target = today  # 防御：ddl 早于今天的日期不越界
        when = "今天" if target == today else "明天"
        # 插入 + 排满时按 ddl 动态腾挪（把 ddl 更晚的已排任务顺延到其 ddl 当天）
        item, touched_days, evicted = _insert_with_eviction(
            db, task, target, task_minutes
        )
        if item is not None:
            placed_dict = _item_to_dict(item)
            plan_action = "scheduled_today" if target == today else "scheduled_tomorrow"
            plan_message = f"已把「{task.title}」排进{when} {item.start_time}-{item.end_time}"
            # 用户画像（Issue #63）：记录新增任务落位事件（只记明细，
            # 不触发学习——插入时段是算法选的，不是用户偏好）
            _record_add_task_event(db, item)
            for ev in evicted:
                plan_message += (
                    f"；已把「{ev['title']}」顺延到{ev['to'][:10]} {ev['to'][11:]}（原本排在{ev['from']}）"
                )
            # 涉及日已确认（已写日历）→ 增量同步 Notion 日历
            if calendar_writer is not None:
                for d in touched_days:
                    if _day_locked(db, d):
                        try:
                            sync = calendar_writer.sync_plan_to_calendar(db, d)
                            plan_message += (
                                f"（{d.isoformat()} 日历同步：新建 {sync.created} / "
                                f"更新 {sync.updated} / 不变 {sync.unchanged}）"
                            )
                        except Exception as exc:  # noqa: BLE001 —— 日历同步尽力而为
                            plan_message += f"（{d.isoformat()} 日历同步失败：{exc}）"
        else:
            plan_action = "deferred"
            plan_message = (
                f"{when}的时间排不下了（{task_minutes} 分钟内无空闲时段，"
                "也没有可顺延的任务），"
                f"可回复「把「{task.title}」挪到 HH:MM」手动安排"
            )
    else:
        plan_action, plan_message = "deferred", (
            "任务已添加，将在下次生成计划时自动纳入（每晚 21:00 预生成次日计划并自动确认）"
        )

    return AddTaskResult(
        task=_task_to_dict(task),
        notion_sync=notion_sync,
        plan_action=plan_action,
        plan_message=plan_message,
        placed=placed_dict,
        evicted=evicted,
    )


def _day_locked(db: Session, day: date) -> bool:
    """该日计划是否已确认锁定（存在 confirmed 项）。"""
    return (
        db.query(PlanItem.id)
        .filter(PlanItem.date == day.isoformat(), PlanItem.status == "confirmed")
        .first()
        is not None
    )


def _record_add_task_event(db: Session, item: PlanItem) -> None:
    """用户画像：新增任务落位 → 记录行为事件（尽力而为，不抛错）。"""
    try:
        subject, _title = profile_store.subject_and_title_for(db, item)
        profile_store.record_event(
            db,
            event_type="add_task",
            plan_date=item.date,
            subject=subject,
            item_type=item.item_type,
            to_bucket=time_bucket_for(item.start_time),
            start_time=item.start_time,
            title=item.title,
        )
        db.commit()
    except Exception:  # noqa: BLE001 —— 画像记录尽力而为
        db.rollback()


def _find_free_slot(
    db: Session,
    day: date,
    minutes: int,
    start_limit: time = time(8, 0),
    end_limit: time = time(22, 0),
) -> tuple[time, time] | None:
    """在 8:00-22:00 找一段与已有计划项不冲突的空闲时段（贪心最早适配）。

    返回 (开始, 结束) 或 None（放不下）。
    """
    items = (
        db.query(PlanItem)
        .filter(PlanItem.date == day.isoformat())
        .order_by(PlanItem.start_time)
        .all()
    )
    busy = sorted((parse_hhmm(i.start_time), parse_hhmm(i.end_time)) for i in items)
    cursor = start_limit
    for s, e in busy:
        if e <= cursor:
            continue
        if s > cursor:
            gap = (s.hour * 60 + s.minute) - (cursor.hour * 60 + cursor.minute)
            if gap >= minutes:
                return cursor, _add_minutes(cursor, minutes)
        cursor = max(cursor, e)
        if cursor >= end_limit:
            break
    if (end_limit.hour * 60 + end_limit.minute) - (cursor.hour * 60 + cursor.minute) >= minutes:
        return cursor, _add_minutes(cursor, minutes)
    return None


def _add_minutes(t: time, minutes: int) -> time:
    """time 加法（分钟），调用方保证结果在合理日内范围。"""
    total = t.hour * 60 + t.minute + minutes
    return time(total // 60, total % 60)


def _insert_task_into_day(
    db: Session,
    task: Task,
    day: date,
    task_minutes: int,
) -> PlanItem | None:
    """增量把任务插入某天计划：找空闲时段安插，**不动已排好的其它项**。

    插入项状态与当日一致（该日已确认 → confirmed，否则 draft）——
    用户无需确认，插入后由调用方同步 Notion 日历。放不下返回 None。
    """
    slot = _find_free_slot(db, day, task_minutes)
    if slot is None:
        return None
    start, end = slot
    item = PlanItem(
        date=day.isoformat(),
        start_time=start.strftime("%H:%M"),
        end_time=end.strftime("%H:%M"),
        item_type="task",
        ref_id=task.id,
        title=task.title,
        status="confirmed" if _day_locked(db, day) else "draft",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _hhmm_duration(start: time, end: time) -> int:
    """HH:MM 时间段长度（分钟）。"""
    return (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)


def _insert_with_eviction(
    db: Session,
    task: Task,
    day: date,
    task_minutes: int,
) -> tuple[PlanItem | None, list[date], list[dict]]:
    """把任务插入目标日；**目标日排满时按 ddl 动态腾挪**（Issue #58）。

    腾挪规则（只适用于新任务有 ddl 的急事）：
    1. 找出目标日已排**任务**里 ddl **晚于**新任务 ddl 的（不紧迫的让位给紧迫的）
    2. 按 ddl 从晚到早尝试，把该任务**顺延到它自己的 ddl 当天**（找得到空档才挪）
    3. 腾出空间后插入新任务；仍放不下则放弃（不动任何安排）

    返回 (插入项或 None, 涉及的日期列表[用于日历同步], 顺延记录列表)。
    只动 task 类型的计划项；课程 / 复习 / 杂项永不挪动。
    """
    touched: list[date] = [day]
    evicted: list[dict] = []
    item = _insert_task_into_day(db, task, day, task_minutes)
    if item is not None:
        return item, touched, evicted
    if task.deadline is None:
        return None, touched, evicted  # 无 ddl 不腾挪（没有可顺延的落点依据）

    candidates = []
    items = (
        db.query(PlanItem)
        .filter(PlanItem.date == day.isoformat(), PlanItem.item_type == "task")
        .all()
    )
    for pi in items:
        t = db.get(Task, pi.ref_id) if pi.ref_id is not None else None
        if t is not None and t.deadline is not None and t.deadline > task.deadline:
            candidates.append((t.deadline, pi))
    for _deadline, pi in sorted(candidates, reverse=True):  # ddl 最晚的先挪
        target_day = parse_date(_deadline)
        if target_day <= day:
            continue
        dur = _hhmm_duration(parse_hhmm(pi.start_time), parse_hhmm(pi.end_time))
        slot = _find_free_slot(db, target_day, dur)
        if slot is None:
            continue  # 该任务 ddl 当天也排满 → 换下一个候选
        start, end = slot
        old_date, old_time = pi.date, f"{pi.start_time}-{pi.end_time}"
        pi.date = target_day.isoformat()
        pi.start_time = start.strftime("%H:%M")
        pi.end_time = end.strftime("%H:%M")
        db.commit()
        if target_day not in touched:
            touched.append(target_day)
        evicted.append(
            {
                "title": pi.title,
                "from": f"{old_date} {old_time}",
                "to": f"{target_day.isoformat()} {pi.start_time}-{pi.end_time}",
            }
        )
        item = _insert_task_into_day(db, task, day, task_minutes)
        if item is not None:
            return item, touched, evicted
    return None, touched, evicted




# ---------- 查询 ----------


def list_courses(db: Session) -> list[dict]:
    """课程列表（含档位）。"""
    rows = db.query(Course).order_by(Course.id).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "tier": c.tier,
            "color": c.color,
            "teacher": c.teacher,
            "notes": c.notes,
        }
        for c in rows
    ]


def _task_to_dict(t: Task) -> dict:
    """Task → 字典（工具返回 / 查询列表用）。"""
    return {
        "id": t.id,
        "title": t.title,
        "task_type": t.task_type,
        "description": t.description,
        "deadline": t.deadline,
        "estimated_minutes": t.estimated_minutes,
        "course_id": t.course_id,
        "course_name": t.course.name if t.course else None,
        "status": t.status,
        "source": t.source,
        "source_ref": t.source_ref,
    }


def list_tasks(db: Session, status: str | None = None) -> list[dict]:
    """任务列表（可按状态过滤：todo/doing/done/cancelled）。"""
    query = db.query(Task)
    if status:
        if status not in ("todo", "doing", "done", "cancelled"):
            raise ValueError(f"未知任务状态: {status!r}（应为 todo/doing/done/cancelled）")
        query = query.filter(Task.status == status)
    rows = query.order_by(Task.id).all()
    return [_task_to_dict(t) for t in rows]


def list_reviews(db: Session, due_date: str | None = None) -> list[dict]:
    """复习计划列表（可按到期日过滤，'YYYY-MM-DD'）。"""
    query = db.query(ReviewSchedule)
    if due_date:
        parse_date(due_date)  # 校验格式
        query = query.filter(ReviewSchedule.due_date == due_date)
    rows = query.order_by(ReviewSchedule.due_date, ReviewSchedule.id).all()
    result: list[dict] = []
    for rs in rows:
        kp = db.get(KnowledgePoint, rs.knowledge_point_id)
        course = db.get(Course, kp.course_id) if kp else None
        result.append(
            {
                "id": rs.id,
                "seq": rs.seq,
                "due_date": rs.due_date,
                "status": rs.status,
                "knowledge_point_id": rs.knowledge_point_id,
                "knowledge_point": kp.title if kp else None,
                "difficulty": kp.difficulty if kp else None,
                "course_id": course.id if course else None,
                "course_name": course.name if course else None,
                "completed_at": rs.completed_at,
            }
        )
    return result
