"""用户画像存储层：行为事件落库、学习规则刷新、手动偏好读写。

把 ``backend/scheduler/profile.py`` 的纯规则计算与 ORM 数据组装起来，
供 service 层埋点（adjust_plan_item / mark_done / add_task）与 MCP 工具
（get_user_profile / update_user_profile）使用。

约定：
- 本模块不提交事务（record_event / refresh_learned_features 只改会话），
  由调用方统一 commit；save_manual_prefs 自己提交（独立工具入口）
- 学习过程尽力而为：service 埋点处包 try/except，画像学习失败不影响
  调整 / 完成 / 添加任务本身
- 学习特征随观察窗口滑动：窗口内证据不再满足阈值时删除该特征
  （画像始终反映「最近 WINDOW_DAYS 天的真实行为」）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.models import (
    KnowledgePoint,
    PlanItem,
    ProfileEvent,
    ReviewSchedule,
    Task,
    UserProfile,
)
from backend.models.base import shanghai_now
from backend.scheduler.profile import (
    TIME_BUCKETS,
    bucket_of_time,
    evaluate_rules,
    subject_for,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")

#: 评估规则的原始素材查询窗口（天）：比规则观察窗口略宽，过滤交给纯模块
EVENT_QUERY_DAYS = 30

#: 手动偏好特征键
KEY_RHYTHM = "rhythm"
KEY_NO_BRAIN_AFTER = "no_brain_after"
KEY_FIXED_ACTIVITIES = "fixed_activities"

#: 周一=0 … 周日=6
WEEKDAY_CN = "一二三四五六日"

_RHYTHM_OPTIONS = ("早鸟", "夜猫", "普通")


@dataclass
class PlannerPrefs:
    """规划器消费的画像偏好（generate_plan 一次读取）。"""

    preferred_buckets: dict[str, str] = field(default_factory=dict)  # 对象键 → 时段
    no_brain_after: time | None = None  # 晚间脑力截止（task/review 不排其后）
    barriers: list[tuple[time, time]] = field(default_factory=list)  # 当日固定安排


def _parse_hhmm(value: str) -> time:
    """'HH:MM' → time（非法抛 ValueError，中文报错）。"""
    try:
        return time.fromisoformat(value)
    except ValueError:
        raise ValueError(f"时间格式应为 HH:MM，收到: {value!r}") from None


def _bucket_of(start_time: str) -> str:
    """'HH:MM' → 时段分桶（morning/afternoon/evening）。"""
    return bucket_of_time(_parse_hhmm(start_time))


# ---------- 学习对象键 ----------


def subject_and_title_for(db: Session, item: PlanItem) -> tuple[str, str]:
    """计划项 → (学习对象键, 展示标题)。

    对象键决定画像聚合维度：task/review 取**课程名**（体现「高数适合晚上」），
    无课程时退回标题；misc 用标题。与 generate_plan 消费侧的取键逻辑一致。
    """
    if item.item_type == "task" and item.ref_id is not None:
        task = db.get(Task, item.ref_id)
        if task is not None:
            return subject_for(task.course.name if task.course else None, task.title), task.title
    if item.item_type == "review" and item.ref_id is not None:
        rs = db.get(ReviewSchedule, item.ref_id)
        if rs is not None:
            kp = db.get(KnowledgePoint, rs.knowledge_point_id)
            title = f"复习 · {kp.title}" if kp else "复习"
            course_name = kp.course.name if kp is not None and kp.course else None
            return subject_for(course_name, title), title
    return subject_for(None, item.title), item.title


# ---------- 事件记录 + 规则刷新 ----------


def record_event(
    db: Session,
    *,
    event_type: str,
    subject: str,
    item_type: str,
    plan_date: str | None = None,
    from_bucket: str | None = None,
    to_bucket: str | None = None,
    start_time: str | None = None,
    title: str | None = None,
) -> None:
    """记录一条行为痕迹（不提交，由调用方 commit）。"""
    if event_type not in ("adjust", "done", "add_task"):
        raise ValueError(f"未知画像事件类型: {event_type!r}")
    if from_bucket is not None and from_bucket not in TIME_BUCKETS:
        raise ValueError(f"未知时段分桶: {from_bucket!r}")
    if to_bucket is not None and to_bucket not in TIME_BUCKETS:
        raise ValueError(f"未知时段分桶: {to_bucket!r}")
    db.add(
        ProfileEvent(
            event_type=event_type,
            occurred_at=shanghai_now(),
            plan_date=plan_date,
            subject=subject,
            item_type=item_type,
            from_bucket=from_bucket,
            to_bucket=to_bucket,
            start_time=start_time,
            title=title,
        )
    )


def refresh_learned_features(db: Session, today: date | None = None) -> None:
    """从近期行为事件重新评估全部学习规则并 upsert 画像特征（不提交）。

    - 规则满足阈值 → 新增或更新特征（value / confidence / evidence / updated_at）
    - 窗口内证据不再满足 → 删除旧特征（画像反映最近行为，不残留过期结论）
    """
    today = today or datetime.now(_SHANGHAI).date()
    since = (today - timedelta(days=EVENT_QUERY_DAYS)).isoformat()
    # 先 flush：让本次会话中刚 record 的事件对查询可见
    # （会话 autoflush=False，不 flush 会漏掉刚写入的事件导致规则计数偏小）
    db.flush()
    rows = (
        db.query(ProfileEvent)
        .filter(ProfileEvent.occurred_at >= since)
        .order_by(ProfileEvent.id)
        .all()
    )
    events = [
        {
            "event_type": e.event_type,
            "occurred_at": e.occurred_at,
            "subject": e.subject,
            "from_bucket": e.from_bucket,
            "to_bucket": e.to_bucket,
            "start_time": e.start_time,
            "title": e.title,
        }
        for e in rows
    ]
    rules = evaluate_rules(events, today)

    current = {
        r.feature_key: r
        for r in db.query(UserProfile)
        .filter(UserProfile.source == "learned")
        .all()
    }
    for rule in rules:
        row = current.get(rule.feature_key)
        if row is None:
            db.add(
                UserProfile(
                    feature_key=rule.feature_key,
                    feature_type=rule.feature_type,
                    value=rule.value,
                    confidence=rule.confidence,
                    evidence=rule.evidence,
                    source="learned",
                )
            )
        elif (
            row.value != rule.value
            or row.confidence != rule.confidence
            or row.evidence != rule.evidence
        ):
            row.value = rule.value
            row.confidence = rule.confidence
            row.evidence = rule.evidence
            row.updated_at = shanghai_now()
    for key, row in current.items():
        if key not in {r.feature_key for r in rules}:
            db.delete(row)


# ---------- 规划器消费 ----------


def load_planner_prefs(db: Session, plan_date: date) -> PlannerPrefs:
    """读取画像偏好供 generate_plan 消费（画像为空时全部为空，行为不变）。"""
    rows = db.query(UserProfile).all()
    prefs = PlannerPrefs()

    prefer: dict[str, str] = {}
    fit: dict[str, str] = {}
    manual: dict[str, UserProfile] = {}
    for r in rows:
        if r.source == "manual":
            manual[r.feature_key] = r
            continue
        if r.feature_type == "prefer_bucket" and r.feature_key.startswith("prefer_bucket."):
            prefer[r.feature_key[len("prefer_bucket."):]] = r.value
        elif r.feature_type == "fit_bucket" and r.feature_key.startswith("fit_bucket."):
            fit[r.feature_key[len("fit_bucket."):]] = r.value
    for subject, bucket in prefer.items():
        prefs.preferred_buckets[subject] = bucket
    for subject, bucket in fit.items():
        prefs.preferred_buckets.setdefault(subject, bucket)  # prefer 优先于 fit

    if KEY_NO_BRAIN_AFTER in manual and manual[KEY_NO_BRAIN_AFTER].value:
        prefs.no_brain_after = _parse_hhmm(manual[KEY_NO_BRAIN_AFTER].value)

    if KEY_FIXED_ACTIVITIES in manual and manual[KEY_FIXED_ACTIVITIES].value:
        try:
            activities = json.loads(manual[KEY_FIXED_ACTIVITIES].value)
        except (json.JSONDecodeError, TypeError):
            activities = []
        weekday = plan_date.weekday()
        for a in activities:
            if weekday in a.get("days", []):
                prefs.barriers.append(
                    (_parse_hhmm(a["start"]), _parse_hhmm(a["end"]))
                )
    prefs.barriers.sort()
    return prefs


def learned_bucket_for(db: Session, subject: str) -> str | None:
    """查询某对象的画像偏好时段（prefer 优先于 fit，无则 None）。"""
    prefs = load_planner_prefs(db, date.today())
    return prefs.preferred_buckets.get(subject)


# ---------- 手动偏好 ----------


def _upsert_manual(db: Session, key: str, feature_type: str, value: str) -> None:
    """写入/更新手动偏好；空值删除该特征（清除设置）。"""
    value = (value or "").strip()
    row = db.query(UserProfile).filter(UserProfile.feature_key == key).first()
    if not value:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(
            UserProfile(
                feature_key=key,
                feature_type=feature_type,
                value=value,
                confidence=0,
                evidence=None,
                source="manual",
            )
        )
    elif row.value != value:
        row.value = value
        row.updated_at = shanghai_now()


def _parse_days(raw: str, index: int) -> list[int]:
    """'每天' / '一三五' → 星期列表（0=周一）。非法抛中文错误。"""
    if raw == "每天":
        return list(range(7))
    days: list[int] = []
    for ch in raw:
        if ch not in WEEKDAY_CN:
            raise ValueError(
                f"固定安排第 {index + 1} 项的 days 应形如「一三五」或「每天」，收到: {raw!r}"
            )
        days.append(WEEKDAY_CN.index(ch))
    if not days:
        raise ValueError(f"固定安排第 {index + 1} 项缺少 days")
    return sorted(days)


def parse_fixed_activities(value: str) -> list[dict]:
    """解析并校验 fixed_activities JSON（'[{"title","days","start","end"}, ...]'）。

    返回规范化列表（days 为星期 int 列表，start/end 为 'HH:MM'），
    校验失败抛中文 ValueError。固定安排之间不允许重叠。
    """
    try:
        raw = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(
            "fixed_activities 应为 JSON 数组，如 "
            '[{"title":"跑步","days":"一三五","start":"17:00","end":"18:00"}]'
        ) from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("fixed_activities 应为非空 JSON 数组")
    if len(raw) > 10:
        raise ValueError("fixed_activities 最多 10 条固定安排")

    result: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"固定安排第 {i + 1} 项应为对象")
        title = str(item.get("title") or "").strip()
        if not title:
            raise ValueError(f"固定安排第 {i + 1} 项缺少 title")
        days = _parse_days(str(item.get("days") or "").strip(), i)
        try:
            start = _parse_hhmm(str(item.get("start") or ""))
            end = _parse_hhmm(str(item.get("end") or ""))
        except ValueError as exc:
            raise ValueError(f"固定安排第 {i + 1} 项「{title}」: {exc}") from exc
        if end <= start:
            raise ValueError(f"固定安排第 {i + 1} 项「{title}」结束时间必须晚于开始时间")
        result.append(
            {
                "title": title,
                "days": days,
                "start": start.strftime("%H:%M"),
                "end": end.strftime("%H:%M"),
            }
        )

    for i, a in enumerate(result):
        for b in result[i + 1:]:
            if set(a["days"]) & set(b["days"]) and _overlap(a, b):
                raise ValueError(
                    f"固定安排「{a['title']}」与「{b['title']}」在相同日期的时间重叠，请调整"
                )
    return result


def _overlap(a: dict, b: dict) -> bool:
    return _parse_hhmm(a["start"]) < _parse_hhmm(b["end"]) and _parse_hhmm(
        b["start"]
    ) < _parse_hhmm(a["end"])


def save_manual_prefs(
    db: Session,
    *,
    rhythm: str | None = None,
    no_brain_after: str | None = None,
    fixed_activities: str | None = None,
) -> dict:
    """手动更新画像偏好并返回更新后的完整画像。

    - 参数 None = 不修改；空字符串 "" = 清除该设置
    - fixed_activities 传 JSON 数组字符串
    - 本函数自己提交事务（独立工具入口）
    """
    if rhythm is not None:
        rhythm_value = (rhythm or "").strip()
        if rhythm_value and rhythm_value not in _RHYTHM_OPTIONS:
            raise ValueError(
                f"作息类型应为 {'/'.join(_RHYTHM_OPTIONS)}（或不填），收到: {rhythm_value!r}"
            )
        _upsert_manual(db, KEY_RHYTHM, "manual", rhythm_value)

    if no_brain_after is not None:
        value = (no_brain_after or "").strip()
        if value:
            _parse_hhmm(value)  # 校验格式
        _upsert_manual(db, KEY_NO_BRAIN_AFTER, "manual", value)

    if fixed_activities is not None:
        value = (fixed_activities or "").strip()
        if value:
            parsed = parse_fixed_activities(value)
            value = json.dumps(parsed, ensure_ascii=False)
        _upsert_manual(db, KEY_FIXED_ACTIVITIES, "manual", value)

    db.commit()
    return get_profile(db)


# ---------- 画像查看 ----------


def _fixed_to_view(activity: dict) -> dict:
    """固定安排存储形态（days=int 列表）→ 展示形态（'一三五'/'每天'）。"""
    days = activity.get("days", [])
    if days == list(range(7)):
        day_text = "每天"
    else:
        day_text = "".join(WEEKDAY_CN[d] for d in sorted(days))
    return {
        "title": activity["title"],
        "days": day_text,
        "start": activity["start"],
        "end": activity["end"],
    }


def get_profile(db: Session) -> dict:
    """组装完整画像：手动偏好 + 学习特征（含证据）+ 最近行为事件。"""
    rows = db.query(UserProfile).order_by(UserProfile.feature_key).all()
    manual: dict[str, str] = {}
    learned: list[dict] = []
    updated_at: str | None = None
    for r in rows:
        if updated_at is None or r.updated_at > updated_at:
            updated_at = r.updated_at
        if r.source == "manual":
            manual[r.feature_key] = r.value
        else:
            learned.append(
                {
                    "feature_key": r.feature_key,
                    "feature_type": r.feature_type,
                    "value": r.value,
                    "confidence": r.confidence,
                    "evidence": r.evidence,
                    "updated_at": r.updated_at,
                }
            )

    fixed_activities: list[dict] = []
    if KEY_FIXED_ACTIVITIES in manual and manual[KEY_FIXED_ACTIVITIES]:
        try:
            fixed_activities = [
                _fixed_to_view(a)
                for a in json.loads(manual[KEY_FIXED_ACTIVITIES])
            ]
        except (json.JSONDecodeError, TypeError):
            fixed_activities = []

    recent = (
        db.query(ProfileEvent)
        .order_by(ProfileEvent.id.desc())
        .limit(10)
        .all()
    )
    recent_events = [
        {
            "event_type": e.event_type,
            "occurred_at": e.occurred_at,
            "plan_date": e.plan_date,
            "subject": e.subject,
            "item_type": e.item_type,
            "from_bucket": e.from_bucket,
            "to_bucket": e.to_bucket,
            "start_time": e.start_time,
            "title": e.title,
        }
        for e in recent
    ]

    return {
        "rhythm": manual.get(KEY_RHYTHM) or "unknown",
        "no_brain_after": manual.get(KEY_NO_BRAIN_AFTER) or None,
        "fixed_activities": fixed_activities,
        "learned": learned,
        "recent_events": recent_events,
        "updated_at": updated_at,
    }
