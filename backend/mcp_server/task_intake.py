"""任务录入 + 计划联动：add_task 及增量插入 / ddl 腾挪。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time, timedelta

from sqlalchemy.orm import Session

from backend.models import Course, PlanItem, Task
from backend.mcp_server._common import (
    DEFAULT_TASK_MINUTES,
    add_minutes,
    clamp_duration,
    get_setting,
    hhmm_duration,
    item_to_dict,
    parse_date,
    parse_hhmm,
    shanghai_today,
)
from backend.mcp_server.plan_lifecycle import record_add_task_event

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
    evicted: list[dict] = field(default_factory=list)  # 腾挪顺延的旧计划项


def task_to_dict(t: Task) -> dict:
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


def day_locked(db: Session, day: date) -> bool:
    """该日计划是否已确认锁定（存在 confirmed 项）。"""
    return (
        db.query(PlanItem.id)
        .filter(PlanItem.date == day.isoformat(), PlanItem.status == "confirmed")
        .first()
        is not None
    )


def find_free_slot(
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
                return cursor, add_minutes(cursor, minutes)
        cursor = max(cursor, e)
        if cursor >= end_limit:
            break
    if (end_limit.hour * 60 + end_limit.minute) - (cursor.hour * 60 + cursor.minute) >= minutes:
        return cursor, add_minutes(cursor, minutes)
    return None


def insert_with_eviction(
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
        dur = hhmm_duration(parse_hhmm(pi.start_time), parse_hhmm(pi.end_time))
        slot = find_free_slot(db, target_day, dur)
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
    slot = find_free_slot(db, day, task_minutes)
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
        status="confirmed" if day_locked(db, day) else "draft",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


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
    today = shanghai_today()
    iso = today.isoformat()
    task_minutes = clamp_duration(
        task.estimated_minutes,
        int(get_setting(db, "task_duration_minutes", str(DEFAULT_TASK_MINUTES))),
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
        item, touched_days, evicted = insert_with_eviction(db, task, target, task_minutes)
        if item is not None:
            placed_dict = item_to_dict(item)
            plan_action = "scheduled_today" if target == today else "scheduled_tomorrow"
            plan_message = f"已把「{task.title}」排进{when} {item.start_time}-{item.end_time}"
            # 用户画像（Issue #63）：记录新增任务落位事件（只记明细，不触发学习）
            record_add_task_event(db, item)
            for ev in evicted:
                plan_message += (
                    f"；已把「{ev['title']}」顺延到{ev['to'][:10]} {ev['to'][11:]}（原本排在{ev['from']}）"
                )
            # 涉及日已确认（已写日历）→ 增量同步 Notion 日历
            if calendar_writer is not None:
                for d in touched_days:
                    if day_locked(db, d):
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
        task=task_to_dict(task),
        notion_sync=notion_sync,
        plan_action=plan_action,
        plan_message=plan_message,
        placed=placed_dict,
        evicted=evicted,
    )
