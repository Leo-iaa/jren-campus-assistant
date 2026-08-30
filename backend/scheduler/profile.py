"""用户画像学习模块（纯逻辑，无 FastAPI / 数据库依赖）。

设计依据 docs/architecture.md 2.5/2.6（规划器 / 自适应）与 Issue #63：

从用户行为痕迹（调整计划 / 标记完成）中学习「什么对象适合什么时段」，
规则全部**可解释**：每条画像特征都带 confidence（观察次数）与 evidence
（中文证据，如「观察到 2026-08-20 至 2026-08-24 共 3 次把「高数」调整到晚上」）。

学习规则（阈值与观察窗口为常量，可调）：

| 规则 | 触发行为 | 学习条件 | 画像特征 |
|------|----------|----------|----------|
| R1 调整偏好 | adjust_plan_item 跨时段挪动 task/review/misc | 观察窗口内同一对象 ≥3 次挪到同一时段 | prefer_bucket.<对象> = 时段 |
| R2 完成时段 | mark_done | 观察窗口内同一对象 ≥3 次在同一时段完成 | fit_bucket.<对象> = 时段 |
| R3 夜猫线索 | 调整 / 完成发生在 21:00 后 | 观察窗口内 ≥3 次 | late_worker = true |

与数据库对接：本模块只做「事件 → 规则」的纯计算；事件落库与特征 upsert
由调用方（backend/mcp_server/profile_store.py）负责。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

#: 时段分桶（对齐 calibration_stats.time_bucket 与规划器窗口）
TIME_BUCKETS = ("morning", "afternoon", "evening")

#: 分桶中文名（证据文本用）
BUCKET_CN = {"morning": "上午", "afternoon": "下午", "evening": "晚上"}

#: 时段边界（分钟，半开区间）：morning [0,720) / afternoon [720,1080) / evening [1080,1440)
_AFTERNOON_START = 12 * 60
_EVENING_START = 18 * 60

#: 学习阈值与观察窗口（常量，可调）
PROFILE_BUCKET_THRESHOLD = 3  # 同一对象同一时段出现次数达到即学习
LATE_WORKER_THRESHOLD = 3  # 21:00 后活动次数达到即判定「夜猫线索」
LATE_WORKER_HOUR = 21  # 21:00 后视为「晚间脑力」活动
WINDOW_DAYS = 14  # 观察窗口（天）：只统计最近 N 天的行为

_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class LearnedRule:
    """一条学习到的画像特征（落库 user_profile，source='learned'）。"""

    feature_key: str  # prefer_bucket.高数 / fit_bucket.高数 / late_worker
    feature_type: str  # prefer_bucket / fit_bucket / late_worker
    value: str  # 'morning' | 'afternoon' | 'evening' | 'true'
    confidence: int  # 观察次数
    evidence: str  # 中文可解释来源


def bucket_of_minutes(minutes: int) -> str:
    """分钟数（0-1439）→ 时段分桶（morning/afternoon/evening）。"""
    if minutes < 0 or minutes >= 1440:
        raise ValueError(f"分钟数超出一天范围（0-1439）：{minutes}")
    if minutes < _AFTERNOON_START:
        return "morning"
    if minutes < _EVENING_START:
        return "afternoon"
    return "evening"


def bucket_of_time(value: time) -> str:
    """time → 时段分桶。"""
    return bucket_of_minutes(value.hour * 60 + value.minute)


def bucket_cn(bucket: str) -> str:
    """分桶英文 → 中文（证据文本用）。"""
    if bucket not in BUCKET_CN:
        raise ValueError(f"未知时段分桶: {bucket!r}（应为 {'/'.join(TIME_BUCKETS)}）")
    return BUCKET_CN[bucket]


def subject_for(course_name: str | None, title: str) -> str:
    """学习对象键：任务/复习取课程名（体现「高数适合晚上」），杂项取标题。"""
    return (course_name or "").strip() or title.strip() or "未命名"


def _to_minutes(value: str) -> int:
    """'HH:MM' → 分钟（非法抛 ValueError，中文报错）。"""
    try:
        t = time.fromisoformat(value)
    except ValueError:
        raise ValueError(f"时间格式应为 HH:MM，收到: {value!r}") from None
    return t.hour * 60 + t.minute


def _parse_occurred(value: str) -> datetime:
    """'YYYY-MM-DD HH:MM:SS'（Asia/Shanghai）→ datetime。"""
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # 兼容 'YYYY-MM-DDTHH:MM:SS' 形态
        return datetime.fromisoformat(value.replace("T", " "))


def _in_window(occurred: str, today: date, window_days: int) -> bool:
    """事件是否落在观察窗口 [today-window_days, today] 内（含当天）。"""
    try:
        when = _parse_occurred(occurred).date()
    except ValueError:
        return False
    return (today - timedelta(days=window_days)) <= when <= today


def _fmt_evidence(
    first: date, last: date, count: int, action: str
) -> str:
    """生成中文证据：观察到 {first} 至 {last} 共 {count} 次{action}。"""
    return f"观察到 {first.isoformat()} 至 {last.isoformat()} 共 {count} 次{action}"


def evaluate_rules(
    events: list[dict],
    today: date,
    *,
    window_days: int = WINDOW_DAYS,
    bucket_threshold: int = PROFILE_BUCKET_THRESHOLD,
    late_threshold: int = LATE_WORKER_THRESHOLD,
) -> list[LearnedRule]:
    """从行为事件明细中评估全部学习规则，返回应落库的画像特征列表。

    事件字典字段（对齐 profile_events 表）：
    ``event_type``（adjust/done/add_task）、``occurred_at``（ISO 时间字符串）、
    ``subject``（学习对象键）、``from_bucket`` / ``to_bucket``（可选）、
    ``start_time``（'HH:MM'，可选）、``title``。

    - R1 只统计**跨时段**的调整（from_bucket != to_bucket）——同段微调
      （如 19:00→20:00 都是晚上）不构成「挪时段」信号
    - R2 按完成时所在时段统计
    - R3 统计调整/完成最终开始时间 ≥ 21:00 的次数（add_task 不参与——插入
      时段是算法选的，不是用户偏好）
    - add_task 事件只作明细留存，不触发任何规则
    - 返回按 feature_key 排序，保证确定性
    """
    windowed = [e for e in events if _in_window(e.get("occurred_at", ""), today, window_days)]

    rules: dict[str, LearnedRule] = {}

    # R1 / R2：按 (事件类型, 对象, 目标时段) 分组计数
    counts: dict[tuple[str, str, str], list[dict]] = {}
    for e in windowed:
        if e.get("event_type") not in ("adjust", "done"):
            continue
        to_bucket = e.get("to_bucket")
        if to_bucket not in TIME_BUCKETS:
            continue
        if e["event_type"] == "adjust" and e.get("from_bucket") == to_bucket:
            continue  # 同段微调不算「挪时段」
        key = (e["event_type"], e.get("subject", ""), to_bucket)
        counts.setdefault(key, []).append(e)

    for (event_type, subject, to_bucket), group in sorted(counts.items()):
        if len(group) < bucket_threshold:
            continue
        dates = sorted(_parse_occurred(e["occurred_at"]).date() for e in group)
        sample_title = group[-1].get("title") or subject
        if event_type == "adjust":
            feature_key, feature_type = f"prefer_bucket.{subject}", "prefer_bucket"
            action = f"把「{sample_title}」调整到{bucket_cn(to_bucket)}"
        else:
            feature_key, feature_type = f"fit_bucket.{subject}", "fit_bucket"
            action = f"在{bucket_cn(to_bucket)}完成「{sample_title}」"
        rules[feature_key] = LearnedRule(
            feature_key=feature_key,
            feature_type=feature_type,
            value=to_bucket,
            confidence=len(group),
            evidence=_fmt_evidence(dates[0], dates[-1], len(group), action),
        )

    # R3：21:00 后安排 / 完成任务（调整与完成都算）
    late_events = []
    for e in windowed:
        if e.get("event_type") not in ("adjust", "done"):
            continue
        start = e.get("start_time")
        if not start:
            continue
        try:
            if _to_minutes(start) >= LATE_WORKER_HOUR * 60:
                late_events.append(e)
        except ValueError:
            continue
    if len(late_events) >= late_threshold:
        dates = sorted(_parse_occurred(e["occurred_at"]).date() for e in late_events)
        evidence = (
            f"观察到 {dates[0].isoformat()} 至 {dates[-1].isoformat()} 共 {len(late_events)} 次"
            f"在 {LATE_WORKER_HOUR}:00 后安排或完成任务"
        )
        rules["late_worker"] = LearnedRule(
            feature_key="late_worker",
            feature_type="late_worker",
            value="true",
            confidence=len(late_events),
            evidence=evidence,
        )

    return [rules[k] for k in sorted(rules)]
