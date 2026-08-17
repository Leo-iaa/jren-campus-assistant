"""时间表规划器（纯逻辑，确定性贪心约束求解，无 FastAPI / 数据库依赖）。

设计依据 docs/vision.md（时间轴 07:33 时间表规划）与 docs/database.md（plan_items）：
- 固定课程块：非释放（`release_slot=False`）为硬屏障，任何项目不可重叠；
  B/C 档释放（`release_slot=True`）的时段可安排其他任务（课程仍出现在输出中）
- 可排项目：作业（task）/ 复习（review）/ 杂项（misc），时长取输入草案 end - start
- 学习时段偏好（study_hours）：复习、作业优先落入该窗口，溢出到其余空闲时段；
  杂项优先级最低，最后填最早空闲
- 输出保证：
  - 不与硬课程冲突、项目两两不重叠（半开区间 [start, end)）
  - UNIQUE(date, start_time)：与课程起始分钟错开、彼此起始时间互异
  - 按开始时间排序
  - 放不下的项目进入 dropped 报告（硬保证：宁可不排也不产生冲突）

算法：贪心最早适配。优先级 = 项目类型（review < task < misc）→ 时长降序 → 标题，
保证确定性（同输入必同输出）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

from backend.scheduler.interfaces import PlanItemDraft

#: 默认可排布时间范围（08:00 - 22:00）
DAY_START = time(8, 0)
DAY_END = time(22, 0)

#: 项目类型优先级（数值越小越先排）
ITEM_PRIORITY: dict[str, int] = {"review": 0, "task": 1, "misc": 2}


@dataclass(frozen=True)
class PlanResult:
    """规划结果：placed 为完整当日计划（含课程块），dropped 为放不下的项目。"""

    placed: list[PlanItemDraft]
    dropped: list[PlanItemDraft] = field(default_factory=list)


def build_plan(
    plan_date: date,
    course_sessions: list[PlanItemDraft],
    tasks: list[PlanItemDraft],
    reviews: list[PlanItemDraft],
    misc_items: list[PlanItemDraft],
    study_hours: tuple[time, time] | None = None,
) -> list[PlanItemDraft]:
    """生成当日建议时间表（对齐 ``interfaces.PlanBuilder`` 协议）。"""
    return build_plan_full(
        plan_date, course_sessions, tasks, reviews, misc_items, study_hours
    ).placed


def build_plan_full(
    plan_date: date,
    course_sessions: list[PlanItemDraft],
    tasks: list[PlanItemDraft],
    reviews: list[PlanItemDraft],
    misc_items: list[PlanItemDraft],
    study_hours: tuple[time, time] | None = None,
) -> PlanResult:
    """生成当日建议时间表，并报告放不下的项目（dropped）。"""
    _validate_study_hours(study_hours)
    _validate_courses(course_sessions)

    course_starts = {_to_minutes(c.start) for c in course_sessions}
    hard_courses = [c for c in course_sessions if not c.release_slot]
    barriers = sorted((_to_minutes(c.start), _to_minutes(c.end)) for c in hard_courses)

    windows = _free_windows(barriers, _to_minutes(DAY_START), _to_minutes(DAY_END))
    study = None
    if study_hours is not None:
        study = (_to_minutes(study_hours[0]), _to_minutes(study_hours[1]))
    windows = _split_windows(windows, study)

    schedulable: list[tuple[PlanItemDraft, int]] = []
    for draft in [*tasks, *reviews, *misc_items]:
        if draft.item_type not in ITEM_PRIORITY:
            raise ValueError(
                f"不可排布的项目类型: {draft.item_type!r}（应为 task/review/misc）"
            )
        duration = _to_minutes(draft.end) - _to_minutes(draft.start)
        if duration <= 0:
            raise ValueError(f"项目时长必须为正: {draft.title!r}（end 必须晚于 start）")
        schedulable.append((draft, duration))

    # 确定性排序：类型优先级 → 时长降序 → 标题
    schedulable.sort(key=lambda x: (ITEM_PRIORITY[x[0].item_type], -x[1], x[0].title))

    placed_items: list[PlanItemDraft] = []
    dropped: list[PlanItemDraft] = []
    for draft, duration in schedulable:
        order = "study_first" if draft.item_type != "misc" else "time"
        hit = _place(windows, course_starts, duration, order)
        if hit is None:
            dropped.append(draft)
            continue
        start_min, windows = hit
        placed_items.append(
            PlanItemDraft(
                date=plan_date,
                start=_from_minutes(start_min),
                end=_from_minutes(start_min + duration),
                item_type=draft.item_type,
                ref_id=draft.ref_id,
                title=draft.title,
            )
        )

    output = [
        PlanItemDraft(
            date=plan_date,
            start=c.start,
            end=c.end,
            item_type="course",
            ref_id=c.ref_id,
            title=c.title,
            release_slot=c.release_slot,
        )
        for c in course_sessions
    ]
    output.extend(placed_items)
    output.sort(key=lambda p: (p.start, p.item_type, p.title))
    return PlanResult(placed=output, dropped=dropped)


# ---------- 校验 ----------


def _validate_study_hours(study_hours: tuple[time, time] | None) -> None:
    if study_hours is not None and _to_minutes(study_hours[0]) >= _to_minutes(study_hours[1]):
        raise ValueError(f"学习时段必须 start < end，收到: {study_hours!r}")


def _validate_courses(course_sessions: list[PlanItemDraft]) -> None:
    for c in course_sessions:
        if _to_minutes(c.end) <= _to_minutes(c.start):
            raise ValueError(f"课程块时长必须为正: {c.title!r}（end 必须晚于 start）")
    starts = [c.start for c in course_sessions]
    if len(set(starts)) != len(starts):
        raise ValueError("课程块起始时间必须互不相同（满足 UNIQUE(date, start_time)）")
    hard = sorted(
        (c for c in course_sessions if not c.release_slot), key=lambda c: c.start
    )
    for prev, cur in zip(hard, hard[1:]):
        if _to_minutes(cur.start) < _to_minutes(prev.end):
            raise ValueError(f"固定课程块之间不允许重叠: {prev.title!r} 与 {cur.title!r}")


# ---------- 时间窗口 ----------


def _free_windows(
    barriers: list[tuple[int, int]], day_start: int, day_end: int
) -> list[tuple[int, int]]:
    """屏障外的空闲窗口（半开区间，分钟）。"""
    windows: list[tuple[int, int]] = []
    cursor = day_start
    for start, end in barriers:
        if start > cursor:
            windows.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < day_end:
        windows.append((cursor, day_end))
    return [(s, e) for s, e in windows if e - s > 0]


def _split_windows(
    windows: list[tuple[int, int]],
    study: tuple[int, int] | None,
) -> list[tuple[str, int, int]]:
    """把空闲窗口拆成「学习时段子窗」与「其余子窗」，返回 (label, start, end)。"""
    if study is None:
        return [("free", ws, we) for ws, we in windows]
    ss, se = study
    parts: list[tuple[str, int, int]] = []
    for ws, we in windows:
        if ws < ss:
            parts.append(("free", ws, min(we, ss)))
        if max(ws, ss) < min(we, se):
            parts.append(("study", max(ws, ss), min(we, se)))
        if we > se:
            parts.append(("free", max(ws, se), we))
    return [p for p in parts if p[2] - p[1] > 0]


def _place(
    windows: list[tuple[str, int, int]],
    occupied_starts: set[int],
    duration: int,
    order: str,
) -> tuple[int, list[tuple[str, int, int]]] | None:
    """把时长 duration 的项目放入最早可用的子窗，返回 (起始分钟, 新窗口列表)。

    - ``order='study_first'``：学习时段子窗优先（按时间序），其余随后（复习/作业）
    - ``order='time'``：全部子窗按时间序（杂项）
    - 起始分钟跳过与课程相同的分钟，保证 UNIQUE(date, start_time)
    - 放置后从左侧消费窗口（窗口缩小/删除）
    """
    if order == "study_first":
        indices = [i for i, w in enumerate(windows) if w[0] == "study"] + [
            i for i, w in enumerate(windows) if w[0] == "free"
        ]
    else:
        indices = list(range(len(windows)))

    for i in indices:
        _label, ws, we = windows[i]
        if we - ws < duration:
            continue
        for s in range(ws, we - duration + 1):
            if s in occupied_starts:
                continue
            new_windows = windows[:i] + windows[i + 1 :]
            if s + duration < we:
                new_windows.append((_label, s + duration, we))
                new_windows.sort(key=lambda w: (w[1], w[2]))
            return s, new_windows
    return None


# ---------- 时间换算 ----------


def _to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _from_minutes(m: int) -> time:
    return time(m // 60, m % 60)


# ---------- 协议实现类 ----------


class PlanBuilderImpl:
    """实现 ``interfaces.PlanBuilder`` 协议的时间表规划器。"""

    def build_plan(
        self,
        plan_date: date,
        course_sessions: list[PlanItemDraft],
        tasks: list[PlanItemDraft],
        reviews: list[PlanItemDraft],
        misc_items: list[PlanItemDraft],
        study_hours: tuple[time, time] | None = None,
    ) -> list[PlanItemDraft]:
        return build_plan(
            plan_date, course_sessions, tasks, reviews, misc_items, study_hours
        )
