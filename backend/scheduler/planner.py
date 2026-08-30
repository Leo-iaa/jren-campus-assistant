"""时间表规划器（纯逻辑，确定性贪心约束求解，无 FastAPI / 数据库依赖）。

设计依据 docs/vision.md（时间轴 07:33 时间表规划）与 docs/database.md（plan_items）：
- 固定课程块：非释放（`release_slot=False`）为硬屏障，任何项目不可重叠；
  B/C 档释放（`release_slot=True`）的时段可安排其他任务（课程仍出现在输出中）
- 可排项目：作业（task）/ 复习（review）/ 杂项（misc），时长取输入草案 end - start
- 学习时段偏好（study_hours）：复习、作业优先落入该窗口，溢出到其余空闲时段；
  杂项优先级最低，最后填最早空闲
- 用户画像偏好（Issue #63，缺省不启用）：
  · 项目草案可带 ``preferred_bucket``（morning/afternoon/evening）——
    优先排进对应时段（如画像学到「高数偏好晚上」）
  · ``brain_curfew``：晚间脑力截止，task/review 不排在该时间之后
  · ``extra_barriers``：额外固定时间块（跑步/吃饭/社团），从空闲时段扣除，
    与课程重叠部分自动裁剪
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

#: 画像偏好时段 → 分钟区间（半开区间；对齐 scheduler/profile.py 分桶边界）
_BUCKET_RANGES: dict[str, tuple[int, int]] = {
    "morning": (0, 12 * 60),
    "afternoon": (12 * 60, 18 * 60),
    "evening": (18 * 60, 24 * 60),
}


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
    brain_curfew: time | None = None,
    extra_barriers: list[tuple[time, time]] | None = None,
) -> list[PlanItemDraft]:
    """生成当日建议时间表（对齐 ``interfaces.PlanBuilder`` 协议）。"""
    return build_plan_full(
        plan_date,
        course_sessions,
        tasks,
        reviews,
        misc_items,
        study_hours,
        brain_curfew=brain_curfew,
        extra_barriers=extra_barriers,
    ).placed


def build_plan_full(
    plan_date: date,
    course_sessions: list[PlanItemDraft],
    tasks: list[PlanItemDraft],
    reviews: list[PlanItemDraft],
    misc_items: list[PlanItemDraft],
    study_hours: tuple[time, time] | None = None,
    brain_curfew: time | None = None,
    extra_barriers: list[tuple[time, time]] | None = None,
) -> PlanResult:
    """生成当日建议时间表，并报告放不下的项目（dropped）。

    可选扩展（画像消费，缺省行为与旧版完全一致）：
    - ``brain_curfew``：晚间脑力截止——task/review 不排在该时间之后
      （misc 不受限，跑步 / 放松类仍可排在晚上）
    - ``extra_barriers``：额外固定时间块（用户画像里的固定生活安排），
      从空闲时段中扣除；与课程重叠部分自动裁剪（不报错）
    - 项目草案的 ``preferred_bucket``：优先排进对应时段（该时段窗口按时间序
      优先尝试，其余窗口随后），画像为空时全部为 None、行为不变
    """
    _validate_study_hours(study_hours)
    _validate_courses(course_sessions)
    _validate_barriers(extra_barriers)

    course_starts = {_to_minutes(c.start) for c in course_sessions}
    hard_courses = [c for c in course_sessions if not c.release_slot]
    barriers = sorted((_to_minutes(c.start), _to_minutes(c.end)) for c in hard_courses)

    windows = _free_windows(barriers, _to_minutes(DAY_START), _to_minutes(DAY_END))
    if extra_barriers:
        extra = [
            (_to_minutes(s), _to_minutes(e)) for s, e in extra_barriers
        ]
        windows = _subtract_barriers(windows, extra)
    study = None
    if study_hours is not None:
        study = (_to_minutes(study_hours[0]), _to_minutes(study_hours[1]))
    windows = _split_windows(windows, study)

    curfew_min = _to_minutes(brain_curfew) if brain_curfew is not None else None

    schedulable: list[tuple[PlanItemDraft, int]] = []
    for draft in [*tasks, *reviews, *misc_items]:
        if draft.item_type not in ITEM_PRIORITY:
            raise ValueError(
                f"不可排布的项目类型: {draft.item_type!r}（应为 task/review/misc）"
            )
        if (
            draft.preferred_bucket is not None
            and draft.preferred_bucket not in _BUCKET_RANGES
        ):
            raise ValueError(
                f"未知偏好时段: {draft.preferred_bucket!r}"
                "（应为 morning/afternoon/evening）"
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
        # 晚间脑力截止只约束 task/review；杂项（运动/放松）不受限
        item_curfew = None if draft.item_type == "misc" else curfew_min
        hit = _place(
            windows,
            course_starts,
            duration,
            order,
            prefer_bucket=draft.preferred_bucket,
            curfew=item_curfew,
        )
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


def _validate_barriers(extra_barriers: list[tuple[time, time]] | None) -> None:
    """额外固定时间块校验：时长必须为正（与课程重叠由裁剪处理，不报错）。"""
    if not extra_barriers:
        return
    for s, e in extra_barriers:
        if _to_minutes(e) <= _to_minutes(s):
            raise ValueError(f"固定时间块时长必须为正: {s} → {e}")


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


def _subtract_barriers(
    windows: list[tuple[int, int]],
    barriers: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """从空闲窗口中扣除额外固定时间块（重叠部分自动裁剪，幂等）。"""
    result: list[tuple[int, int]] = []
    for ws, we in windows:
        pieces = [(ws, we)]
        for bs, be in barriers:
            next_pieces: list[tuple[int, int]] = []
            for ps, pe in pieces:
                if be <= ps or bs >= pe:
                    next_pieces.append((ps, pe))
                    continue
                if bs > ps:
                    next_pieces.append((ps, bs))
                if be < pe:
                    next_pieces.append((be, pe))
            pieces = next_pieces
        result.extend(pieces)
    return [(s, e) for s, e in result if e - s > 0]


def _split_windows(
    windows: list[tuple[int, int]],
    study: tuple[int, int] | None,
) -> list[tuple[str, int, int]]:
    """把空闲窗口拆成「学习时段子窗」与「其余子窗」，返回 (label, start, end)。

    同时在时段分桶边界（12:00 / 18:00）处再切一刀，让画像偏好时段定位精确：
    跨边界窗口若不切分，偏好晚上的项目会落在窗口左缘（下午）而违背偏好
    （与学习时段偏好同款陷阱，见 scheduling-algorithms skill 笔记）。
    """
    if study is None:
        parts: list[tuple[str, int, int]] = [("free", ws, we) for ws, we in windows]
    else:
        ss, se = study
        parts = []
        for ws, we in windows:
            if ws < ss:
                parts.append(("free", ws, min(we, ss)))
            if max(ws, ss) < min(we, se):
                parts.append(("study", max(ws, ss), min(we, se)))
            if we > se:
                parts.append(("free", max(ws, se), we))

    # 按时段分桶边界再切分（12:00 / 18:00）
    final: list[tuple[str, int, int]] = []
    for label, ws, we in parts:
        cuts = sorted({ws, we, 12 * 60, 18 * 60})
        for a, b in zip(cuts, cuts[1:]):
            lo, hi = max(ws, a), min(we, b)
            if hi - lo > 0:
                final.append((label, lo, hi))
    return final


def _place(
    windows: list[tuple[str, int, int]],
    occupied_starts: set[int],
    duration: int,
    order: str,
    prefer_bucket: str | None = None,
    curfew: int | None = None,
) -> tuple[int, list[tuple[str, int, int]]] | None:
    """把时长 duration 的项目放入最早可用的子窗，返回 (起始分钟, 新窗口列表)。

    - ``order='study_first'``：学习时段子窗优先（按时间序），其余随后（复习/作业）
    - ``order='time'``：全部子窗按时间序（杂项）
    - ``prefer_bucket``：画像偏好时段——该时段内窗口（按时间序）优先尝试，
      其余窗口随后（同段微调不影响时段归属，只影响窗口顺序）
    - ``curfew``：脑力截止分钟——窗口结束时间裁剪到 curfew（task/review 用；
      misc 传 None 不受限）
    - 起始分钟跳过与课程相同的分钟，保证 UNIQUE(date, start_time)
    - 放置后从左侧消费窗口（窗口缩小/删除）
    """
    if order == "study_first":
        indices = [i for i, w in enumerate(windows) if w[0] == "study"] + [
            i for i, w in enumerate(windows) if w[0] == "free"
        ]
    else:
        indices = list(range(len(windows)))

    if prefer_bucket is not None:
        bucket_start, bucket_end = _BUCKET_RANGES[prefer_bucket]

        def _in_bucket(w: tuple[str, int, int]) -> bool:
            _label, ws, we = w
            return ws < bucket_end and we > bucket_start

        indices = [i for i in indices if _in_bucket(windows[i])] + [
            i for i in indices if not _in_bucket(windows[i])
        ]

    for i in indices:
        _label, ws, we = windows[i]
        if curfew is not None:
            we = min(we, curfew)
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
        brain_curfew: time | None = None,
        extra_barriers: list[tuple[time, time]] | None = None,
    ) -> list[PlanItemDraft]:
        return build_plan(
            plan_date,
            course_sessions,
            tasks,
            reviews,
            misc_items,
            study_hours,
            brain_curfew=brain_curfew,
            extra_barriers=extra_barriers,
        )
