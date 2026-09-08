"""计划项生命周期：确认（写 Notion 日历）/ 调整 / 完成（校准 + 画像学习）。"""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from backend.models import (
    CalibrationStat,
    KnowledgePoint,
    PlanItem,
    PlanVersion,
    ReviewSchedule,
    Task,
)
from backend.mcp_server import profile_store
from backend.mcp_server._common import (
    ConfirmResult,
    _SHANGHAI,
    duration_minutes,
    item_to_dict,
    parse_date,
    parse_hhmm,
    time_bucket_for,
)
from backend.scheduler.calibration import TIME_BUCKETS


def _latest_version(db: Session, iso: str) -> int | None:
    row = (
        db.query(PlanVersion)
        .filter(PlanVersion.date == iso)
        .order_by(PlanVersion.version.desc())
        .first()
    )
    return row.version if row else None


def _sync_result_dict(sync) -> dict:
    """CalendarSyncResult → 字典。"""
    return {"created": sync.created, "updated": sync.updated, "unchanged": sync.unchanged}


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
                payload=json.dumps([item_to_dict(it) for it in items], ensure_ascii=False),
                confirmed_at=datetime.now(_SHANGHAI).isoformat(timespec="seconds"),
            )
        )
    db.commit()

    notion_sync: dict | None = None
    if calendar_writer is not None:
        try:
            notion_sync = _sync_result_dict(calendar_writer.sync_plan_to_calendar(db, plan_date))
        except Exception as exc:  # noqa: BLE001 —— 日历写入尽力而为，失败不阻断确认
            notion_sync = {"error": str(exc)}

    return ConfirmResult(
        plan_date=plan_date,
        confirmed_count=len(items),
        version=version,
        notion_sync=notion_sync,
    )


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
        if (new_start < o_end and new_end > o_start) or new_start == o_start:
            raise ValueError(
                f"时间冲突：与「{other.title}」({other.start_time}-{other.end_time}) 重叠或起始时间相同"
            )

    item.start_time = new_start.strftime("%H:%M")
    item.end_time = new_end.strftime("%H:%M")
    item.status = "adjusted"
    if title:
        item.title = title
    db.commit()
    db.refresh(item)
    result = item_to_dict(item)

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
                sync = calendar_writer.sync_plan_to_calendar(db, parse_date(item.date))
                result["notion_sync"] = _sync_result_dict(sync)
            except Exception as exc:  # noqa: BLE001 —— 日历同步尽力而为
                result["notion_sync"] = {"error": str(exc)}
        else:
            result["notion_sync"] = None  # 未绑定 Notion / 未配置日历库
    return result


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
        return item_to_dict(item)

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
        _record_calibration(db, item, duration_minutes(item), actual_minutes)
        calibration_recorded = True

    db.commit()
    result = item_to_dict(item)
    result["calibration_recorded"] = calibration_recorded
    if linked_review is not None:
        result["linked_review_status"] = linked_review.status

    _learn_from_completion(db, item)
    return result


# ---------- 画像学习（尽力而为，失败不影响主操作） ----------


def _learn_from_adjustment(db: Session, item: PlanItem, old_start: str) -> None:
    """调整行为 → 记录事件 + 刷新学习特征。"""
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
    """完成行为 → 记录事件 + 刷新学习特征。"""
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


def record_add_task_event(db: Session, item: PlanItem) -> None:
    """新增任务落位 → 记录行为事件（只记明细，不触发学习——插入时段是算法选的）。"""
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
