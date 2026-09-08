"""计划生成：把当日课程 / 任务 / 复习 / 杂项组装成草案并落库。

生成语义（幂等、不破坏已确认计划）：
- 某日已有 confirmed 计划项时不再自动重排（避免覆盖用户已确认的安排），
  返回 skipped 说明，改动请走 adjust_plan_item
- 其余情况（全部为 draft/adjusted 或混有 done）重新生成：仅替换 status 为
  draft / adjusted 的旧计划项，done 项保留不动
- 与保留项（done）起始时间冲突的新草案跳过并在结果中报告
  （保持 UNIQUE(date, start_time)）
"""
from __future__ import annotations

from datetime import date, time

from sqlalchemy.orm import Session

from backend.models import Course, CourseSession, KnowledgePoint, MiscItem, PlanItem, ReviewSchedule, Task
from backend.mcp_server import profile_store
from backend.mcp_server._common import (
    DEFAULT_REVIEW_MINUTES,
    DEFAULT_TASK_MINUTES,
    ITEM_TYPE_LABELS,
    S_REVIEW_MINUTES,
    GeneratePlanResult,
    clamp_duration,
    get_setting,
    minutes_to_time,
    parse_hhmm,
    parse_study_hours,
)
from backend.scheduler.interfaces import PlanItemDraft
from backend.scheduler.planner import build_plan_full
from backend.scheduler.profile import bucket_of_time, subject_for

#: 无任务可标注时 B 档课程的回退文案
B_FALLBACK_NOTE = "可做别的事，效率减半"


def _plan_b_annotations(
    sessions: list[CourseSession],
    unexpired_tasks: list[Task],
    s_review_drafts: list[PlanItemDraft],
) -> tuple[dict[int, str], set[int], set[int]]:
    """给每门 B 档课挑一件「课上可做的事」（Issue #76）。

    优先级：① 未完成任务（ddl 升序，越急越先在课上写）
            ② S 档课后复习（水课可用来复习，前提是该水课不早于那门 S 档课下课）
    返回 (课程id → 标注文案, 被选走的任务id集, 被选走的 S 档复习下标集)。
    """
    b_annotation: dict[int, str] = {}
    used_tasks: set[int] = set()
    used_reviews: set[int] = set()
    for s in sessions:
        if s.course.tier != "B":
            continue
        candidates = [t for t in unexpired_tasks if t.id not in used_tasks]
        if candidates:
            candidates.sort(key=lambda t: (t.deadline or "9999-12-31", t.id))
            pick = candidates[0]
            used_tasks.add(pick.id)
            b_annotation[s.id] = f"可写{pick.title}"
            continue
        review_candidates = [
            (idx, d)
            for idx, d in enumerate(s_review_drafts)
            if idx not in used_reviews
            and d.not_before is not None
            and d.not_before <= parse_hhmm(s.start_time)
        ]
        if review_candidates:
            idx, pick_review = review_candidates[0]
            used_reviews.add(idx)
            core = pick_review.title.removeprefix("复习 · ").removesuffix("（课后）")
            b_annotation[s.id] = f"可复习{core}"
            continue
        b_annotation[s.id] = B_FALLBACK_NOTE
    return b_annotation, used_tasks, used_reviews


def generate_plan(db: Session, plan_date: date) -> GeneratePlanResult:
    """生成某日建议计划并落库（draft 状态），返回放置 / 放不下 / 跳过明细。"""
    task_minutes = int(get_setting(db, "task_duration_minutes", str(DEFAULT_TASK_MINUTES)))
    review_minutes = int(get_setting(db, "review_duration_minutes", str(DEFAULT_REVIEW_MINUTES)))
    if task_minutes <= 0 or review_minutes <= 0:
        raise ValueError("设置 task_duration_minutes / review_duration_minutes 必须为正整数")

    iso = plan_date.isoformat()

    # 1. 当日课程时间块（周次区间 starts_on/ends_on 过滤，支持前后半学期错峰）
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
        if (s.starts_on is None or s.starts_on <= iso) and (s.ends_on is None or s.ends_on >= iso)
    ]

    # 2. 用户画像偏好（Issue #63）：偏好时段 / 晚间脑力截止 / 固定安排屏障
    prefs = profile_store.load_planner_prefs(db, plan_date)

    # 3. S 档课后复习草案（Issue #74）：not_before 紧排课后
    s_review_drafts = [
        PlanItemDraft(
            date=plan_date,
            start=time(0, 0),  # 占位：规划器只取 end-start 作为时长
            end=minutes_to_time(S_REVIEW_MINUTES),
            item_type="review",
            ref_id=None,
            title=f"复习 · {s.course.name}（课后）",
            not_before=parse_hhmm(s.end_time),
        )
        for s in sessions
        if s.course.tier == "S"
    ]

    # 4. 任务 / 复习 / 杂项草案
    pending_tasks = db.query(Task).filter(Task.status.in_(["todo", "doing"])).order_by(Task.id).all()
    unexpired_tasks = [t for t in pending_tasks if not (t.deadline and t.deadline[:10] < iso)]

    b_annotation, used_tasks, used_s_reviews = _plan_b_annotations(
        sessions, unexpired_tasks, s_review_drafts
    )

    course_drafts = [
        PlanItemDraft(
            date=plan_date,
            start=parse_hhmm(s.start_time),
            end=parse_hhmm(s.end_time),
            item_type="course",
            ref_id=s.id,
            title=(
                f"{s.course.name}（{b_annotation.get(s.id, B_FALLBACK_NOTE)}）"
                if s.course.tier == "B"
                else s.course.name
            ),
            # release_slot 为预留字段：B 档改为标题标注，课程一律硬块
            release_slot=False,
        )
        for s in sessions
    ]

    # 被标注选走的任务不再单独排（就在 B 档课上写）；已过期的不自动排
    task_drafts = [
        PlanItemDraft(
            date=plan_date,
            start=time(0, 0),
            end=minutes_to_time(clamp_duration(t.estimated_minutes, task_minutes)),
            item_type="task",
            ref_id=t.id,
            title=t.title,
            preferred_bucket=prefs.preferred_buckets.get(
                subject_for(t.course.name if t.course else None, t.title)
            ),
        )
        for t in pending_tasks
        if t.id not in used_tasks and not (t.deadline and t.deadline[:10] < iso)
    ]

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
        review_drafts.append(
            PlanItemDraft(
                date=plan_date,
                start=time(0, 0),
                end=minutes_to_time(clamp_duration(review_minutes, review_minutes)),
                item_type="review",
                ref_id=rs.id,
                title=title,
                preferred_bucket=prefs.preferred_buckets.get(
                    subject_for(kp.course.name if kp and kp.course else None, title)
                ),
            )
        )

    misc_drafts: list[PlanItemDraft] = []
    skipped: list[str] = []
    for m in db.query(MiscItem).filter(MiscItem.status == "todo").order_by(MiscItem.id).all():
        minutes = clamp_duration(m.duration_minutes, 0)
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
        misc_drafts.append(
            PlanItemDraft(
                date=plan_date,
                start=time(0, 0),
                end=minutes_to_time(minutes),
                item_type="misc",
                ref_id=m.id,
                title=m.title,
                preferred_bucket=declared_bucket
                or prefs.preferred_buckets.get(subject_for(None, m.title)),
            )
        )

    # 5. 规划器求解（确定性贪心，保证不冲突 + UNIQUE(start)）
    result = build_plan_full(
        plan_date,
        course_drafts,
        task_drafts,
        # 被 B 档水课标注选走的 S 档课后复习不再单独排（就在水课上复习）
        review_drafts + [d for i, d in enumerate(s_review_drafts) if i not in used_s_reviews],
        misc_drafts,
        parse_study_hours(get_setting(db, "study_hours", "")),
        brain_curfew=prefs.no_brain_after,
        extra_barriers=prefs.barriers or None,
    )
    dropped = [f"{ITEM_TYPE_LABELS[d.item_type][1]}「{d.title}」" for d in result.dropped]

    # 6. 落库：替换 draft/adjusted，保留 done（防冲突占用起始分钟）；
    #    已确认的计划不自动重排（避免覆盖用户安排）
    if db.query(PlanItem.id).filter(PlanItem.date == iso, PlanItem.status == "confirmed").first():
        return GeneratePlanResult(
            plan_date=plan_date,
            placed_count=0,
            dropped=[],
            skipped=["该日计划已确认，未重新生成（如需调整请使用 adjust_plan_item）"],
        )

    kept_starts = {
        k.start_time
        for k in db.query(PlanItem).filter(PlanItem.date == iso, PlanItem.status == "done").all()
    }
    for old in (
        db.query(PlanItem).filter(PlanItem.date == iso, PlanItem.status.in_(["draft", "adjusted"])).all()
    ):
        db.delete(old)
    # 先落地删除：SQLAlchemy flush 顺序默认「先插入后删除」，
    # 若新草案与旧 draft 同 start_time，不先 DELETE 会撞 UNIQUE(date, start_time)
    db.flush()

    placed_count = 0
    for draft in result.placed:
        if draft.start.strftime("%H:%M") in kept_starts:
            skipped.append(
                f"{ITEM_TYPE_LABELS[draft.item_type][1]}「{draft.title}」与已确认项起始时间冲突，跳过"
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
        plan_date=plan_date, placed_count=placed_count, dropped=dropped, skipped=skipped
    )
