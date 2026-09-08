"""共享工具：时区、解析、时长规范化、结果数据结构。

``service.py`` 门面从这里 re-export；新代码请直接从本模块导入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from backend.models import PlanItem, Setting

_SHANGHAI = ZoneInfo("Asia/Shanghai")

#: 计划项类型的 emoji 与中文名（预览文本用）
ITEM_TYPE_LABELS: dict[str, tuple[str, str]] = {
    "course": ("📚", "课程"),
    "task": ("📝", "作业"),
    "review": ("🔁", "复习"),
    "misc": ("🗓", "杂项"),
}

#: 校准时段分桶边界（对齐 calibration_stats.time_bucket）
MORNING_END = time(12, 0)
AFTERNOON_END = time(18, 0)

#: 默认时长（分钟），可用 settings 表覆盖
DEFAULT_TASK_MINUTES = 60
DEFAULT_REVIEW_MINUTES = 30

#: S 档课后复习时长（分钟，Issue #74：每门 S 档课程上完自动安排 1 小时复习）
S_REVIEW_MINUTES = 60

#: 单条目时长上限（分钟）：超过视为异常，clamp 以免 time() 溢出（hour>23）崩溃
MAX_DURATION_MINUTES = 720


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


def get_setting(db: Session, key: str, default: str) -> str:
    """读取 settings 键值表（不存在返回默认值）。"""
    row = db.query(Setting).filter(Setting.key == key).first()
    return row.value if row is not None else default


def item_to_dict(item: PlanItem) -> dict:
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
    if t < MORNING_END:
        return "morning"
    if t < AFTERNOON_END:
        return "afternoon"
    return "evening"


def minutes_to_time(minutes: int) -> time:
    """分钟数 → time（越界抛中文错误，防御来自配置 / 数据的异常时长）。"""
    if minutes < 0 or minutes >= 1440:
        raise ValueError(f"时长超出合理范围（0-1439 分钟）：{minutes}")
    return time(minutes // 60, minutes % 60)


def clamp_duration(minutes: int | None, default: int) -> int:
    """规范化任务 / 复习时长：缺失或非法用默认值；超大值 clamp 到上限。"""
    if not minutes or minutes <= 0:
        return default
    return min(minutes, MAX_DURATION_MINUTES)


def parse_study_hours(value: str) -> tuple[time, time] | None:
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


def add_minutes(t: time, minutes: int) -> time:
    """time 加法（分钟），调用方保证结果在合理日内范围。"""
    total = t.hour * 60 + t.minute + minutes
    return time(total // 60, total % 60)


def hhmm_duration(start: time, end: time) -> int:
    """HH:MM 时间段长度（分钟）。"""
    return (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)


def duration_minutes(item: PlanItem) -> int:
    """计划项时长（分钟）。"""
    return hhmm_duration(parse_hhmm(item.start_time), parse_hhmm(item.end_time))
