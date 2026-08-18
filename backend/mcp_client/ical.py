"""iCal 课表解析 adapter。

输入：教务系统导出的 .ics（如 WakeUpSchedule 导出，见用户附件样例）：
- ``DTSTART/DTEND`` 带 ``TZID=Asia/Shanghai``
- ``RRULE:FREQ=WEEKLY;UNTIL=...;INTERVAL=1``
- 同一课程（SUMMARY）可能拆成多个 VEVENT（教师/教室中途更换）→ 按
  ``(课程, 星期, 开始时间)`` 去重合并，保留信息最新的一份

输出：``CourseSessionItem`` 列表（对应 courses + course_sessions 落库）。
手动维护兜底：课程/时间块既有 CRUD API 保留，同步默认 merge 模式不覆盖手改字段。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar

from backend.mcp_client.models import CourseSessionItem

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


@dataclass(frozen=True)
class RawEvent:
    """单个 VEVENT 的归一化结果（合并前的中间形态）。"""

    course_name: str
    day_of_week: int  # 0=周一
    start_time: str
    end_time: str
    location: str | None
    teacher: str | None
    first_date: date  # 首次上课日期（用于「取最新」排序）
    uid: str


def _local_datetime(dt: date | datetime) -> datetime:
    """把 DTSTART/DTEND 规整为带 +08:00 的本地时间（naive 视为本地时间）。"""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_SHANGHAI)
        return dt.astimezone(_SHANGHAI)
    # 全天事件（VALUE=DATE）无时刻，不属于课程时间块模板 → 上层跳过
    raise ValueError("全天事件不支持")


def _split_location(location: str) -> tuple[str | None, str | None]:
    """把 ``'实验大楼B209-1 陈建全'`` 拆成 (教室, 教师)。

    规则：含 ASCII 字母/数字的 token 视为教室（如 教西B2-301）；
    纯中文 token 视为教师（如 陈建全）。
    """
    tokens = location.split()
    rooms: list[str] = []
    teachers: list[str] = []
    for tok in tokens:
        if re.search(r"[A-Za-z0-9]", tok):
            rooms.append(tok)
        elif _CJK_RE.search(tok) and len(tok) >= 2:
            teachers.append(tok)
        else:
            rooms.append(tok)
    return (" ".join(rooms) or None), (" ".join(teachers) or None)


def _extract_event(comp: icalendar.cal.Component) -> tuple[RawEvent | None, list[str]]:
    """单个 VEVENT → RawEvent（跳过/告警信息随 warnings 返回）。"""
    warnings: list[str] = []
    summary = str(comp.get("SUMMARY") or "").strip()
    if not summary:
        return None, ["跳过无 SUMMARY 的事件"]
    dtstart = comp.get("DTSTART")
    dtend = comp.get("DTEND")
    if dtstart is None or dtend is None:
        return None, [f"跳过无时间事件：{summary}"]
    try:
        start = _local_datetime(dtstart.dt)
        end = _local_datetime(dtend.dt)
    except ValueError:
        return None, [f"跳过全天事件：{summary}"]
    if end <= start:
        return None, [f"跳过时间异常事件（结束不晚于开始）：{summary}"]

    rrule = comp.get("RRULE")
    if rrule is None:
        return None, [f"跳过非重复事件：{summary}（无 RRULE，单次事件不构成每周课程模板）"]
    freq = rrule.get("FREQ")
    if isinstance(freq, list):
        freq = freq[0] if freq else None
    if str(freq).upper() != "WEEKLY":
        return None, [f"跳过非每周重复事件：{summary}（FREQ={freq}）"]

    room, teacher = _split_location(str(comp.get("LOCATION") or ""))
    if room is None and teacher is None:
        # 兜底：DESCRIPTION 通常为 「第X-Y节\\n教室\\n教师」
        desc_lines = [ln.strip() for ln in str(comp.get("DESCRIPTION") or "").splitlines() if ln.strip()]
        if len(desc_lines) >= 2:
            room, teacher = _split_location(" ".join(desc_lines[1:]))

    return (
        RawEvent(
            course_name=summary,
            day_of_week=start.weekday(),
            start_time=start.strftime("%H:%M"),
            end_time=end.strftime("%H:%M"),
            location=room,
            teacher=teacher,
            first_date=start.date(),
            uid=str(comp.get("UID") or ""),
        ),
        warnings,
    )


def parse_ics(content: str) -> tuple[list[CourseSessionItem], list[str]]:
    """解析 .ics 文本 → (去重合并后的课程时间块, 警告列表)。"""
    warnings: list[str] = []
    calendar = icalendar.Calendar.from_ical(content)

    raw_events: list[RawEvent] = []
    for comp in calendar.walk("VEVENT"):
        event, event_warnings = _extract_event(comp)
        warnings.extend(event_warnings)
        if event is not None:
            raw_events.append(event)

    # 去重合并：同一 (课程, 星期, 开始时间) 保留「首次上课日期最晚」的事件
    # （教师/教室更换时，后段信息更新；按 first_date 升序处理，后者覆盖前者）
    merged: dict[tuple[str, int, str], RawEvent] = {}
    for event in sorted(raw_events, key=lambda e: (e.course_name, e.day_of_week, e.start_time, e.first_date)):
        merged[(event.course_name, event.day_of_week, event.start_time)] = event

    items = [
        CourseSessionItem(
            course_name=event.course_name,
            day_of_week=event.day_of_week,
            start_time=event.start_time,
            end_time=event.end_time,
            location=event.location,
            teacher=event.teacher,
        )
        for event in merged.values()
    ]
    return items, warnings


class IcalAdapter:
    """解析 .ics 文件或内容为课程时间块列表（纯解析，不落库）。"""

    def __init__(self, ics_path: str | None = None, ics_content: str | None = None) -> None:
        if ics_path is None and ics_content is None:
            raise ValueError("需要提供 ics_path 或 ics_content 之一")
        self._ics_path = ics_path
        self._ics_content = ics_content

    def _load(self) -> str:
        if self._ics_content is not None:
            return self._ics_content
        path = Path(self._ics_path)
        if not path.is_file():
            raise ValueError(f"iCal 文件不存在：{self._ics_path}")
        return path.read_text(encoding="utf-8", errors="replace")

    def parse(self) -> tuple[list[CourseSessionItem], list[str]]:
        """解析 → (课程时间块列表, 警告列表)。"""
        return parse_ics(self._load())
