"""遗忘曲线复习调度器（纯逻辑，无 FastAPI / 数据库依赖）。

设计依据 docs/vision.md「复习策略：课程档位制」与 docs/architecture.md 2.4：

- 档位序列（每门课在设置页指定，一次设置长期生效）：
  - S 档：当晚 + 第 1/2/4/7/15 天
  - A 档：当晚 + 第 1/2/4/7/15 天
  - B 档：当晚 + 第 1/7 天
  - C 档：不安排复习（仅跟踪作业 / 考试 deadline）
- 难度微调（1-5）：
  - 难度 ≥ 4：首次复习提前至课后 2 小时（日期不变，note 标注「课后 2 小时」）
  - 难度 ≤ 2：跳过当天晚上那次复习
  - S 档难度 ≥ 4：额外增加一次复习（插在第 2 天与第 4 天之间，即第 3 天）
- 每日复习上限（默认 8）：批量生成时超出顺延次日（FIFO 溢出队列，只推后不提前）
- 状态流转：pending / overdue → done / skipped；终态（done / skipped）不可再流转

对外接口：
- :func:`build_review_schedule`：单个知识点（对齐 interfaces.ReviewScheduler 协议）
- :func:`apply_daily_cap`：批量按日上限顺延（分组输入输出，组内顺序保持）
- :func:`classify_status` / :func:`transition_status`：复习计划状态流转
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import date, timedelta

from backend.scheduler.interfaces import ReviewDraft

# ---------- 档位与参数 ----------

#: 各档位复习间隔（距首次复习日的天数，0 = 当天晚上）
TIER_OFFSETS: dict[str, tuple[int, ...]] = {
    "S": (0, 1, 2, 4, 7, 15),
    "A": (0, 1, 2, 4, 7, 15),
    "B": (0, 1, 7),
    "C": (),
}

VALID_TIERS = frozenset(TIER_OFFSETS)
VALID_DIFFICULTIES = range(1, 6)

EVENING_OFFSET = 0  # 当天晚上
HARD_THRESHOLD = 4  # 难度 ≥ 4：提前首次复习 / S 档额外一次
EASY_THRESHOLD = 2  # 难度 ≤ 2：跳过当晚
EXTRA_OFFSET = 3  # S 档难度≥4 的额外复习：插在第 2 天与第 4 天之间

#: 复习计划状态
PENDING = "pending"
DONE = "done"
SKIPPED = "skipped"
OVERDUE = "overdue"
TERMINAL_STATUSES = frozenset({DONE, SKIPPED})


@dataclass(frozen=True)
class ReviewRequest:
    """批量调度输入：一个知识点的复习请求。"""

    ref_id: int | None
    course_tier: str
    difficulty: int
    first_date: date


# ---------- 核心算法 ----------


def build_review_schedule(
    course_tier: str,
    difficulty: int,
    first_date: date,
    daily_cap: int = 8,
) -> list[ReviewDraft]:
    """生成单个知识点的完整复习序列。

    参数：
        course_tier: 课程档位 'S' | 'A' | 'B' | 'C'
        difficulty: 知识点难度 1-5
        first_date: 首次复习日期（通常为上课当天）
        daily_cap: 每日复习上限。单个知识点自身序列每天至多一次复习，
            故该参数在单点场景不生效（批量场景见 :func:`apply_daily_cap`）。
    返回：
        按复习次序排列的 :class:`ReviewDraft` 列表；C 档返回空列表。
    异常：
        ValueError: 档位或难度非法。
    """
    _validate(course_tier, difficulty)
    offsets = _offsets_for(course_tier, difficulty)
    drafts: list[ReviewDraft] = []
    for seq, offset in enumerate(offsets, start=1):
        note = ""
        if offset == EVENING_OFFSET and difficulty >= HARD_THRESHOLD:
            note = "难度≥4：首次复习提前至课后 2 小时"
        elif offset == EXTRA_OFFSET and difficulty >= HARD_THRESHOLD:
            note = "S 档难度≥4：额外增加一次复习"
        drafts.append(
            ReviewDraft(seq=seq, due_date=first_date + timedelta(days=offset), note=note)
        )
    return drafts


def _offsets_for(course_tier: str, difficulty: int) -> tuple[int, ...]:
    """档位 × 难度 → 复习间隔（天数）序列。"""
    offsets = TIER_OFFSETS[course_tier]
    if difficulty <= EASY_THRESHOLD and EVENING_OFFSET in offsets:
        offsets = tuple(o for o in offsets if o != EVENING_OFFSET)
    if course_tier == "S" and difficulty >= HARD_THRESHOLD:
        offsets = tuple(sorted(offsets + (EXTRA_OFFSET,)))
    return offsets


def _validate(course_tier: str, difficulty: int) -> None:
    if course_tier not in VALID_TIERS:
        raise ValueError(f"未知课程档位: {course_tier!r}（应为 S/A/B/C）")
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError(f"难度必须在 1-5 之间，收到: {difficulty!r}")


# ---------- 批量生成 + 每日上限 ----------


def build_schedule_with_cap(
    requests: list[ReviewRequest],
    daily_cap: int = 8,
) -> list[list[ReviewDraft]]:
    """批量生成复习序列并应用每日上限。

    返回与 ``requests`` 一一对应的分组列表（组内按 seq 顺序），
    所有组的到期日已按上限顺延。
    """
    grouped = [build_review_schedule(r.course_tier, r.difficulty, r.first_date) for r in requests]
    return apply_daily_cap(grouped, daily_cap)


def apply_daily_cap(
    grouped: list[list[ReviewDraft]],
    cap: int,
) -> list[list[ReviewDraft]]:
    """按每日上限顺延复习日期（纯函数，不改动输入）。

    规则（确定性 FIFO）：
    1. 全部复习点按（到期日, 组序号, seq）排序，同日先到先得；
    2. 逐日推进：先消化前一日溢出的队列，再放入当日到期的；
    3. 某日名额占满（cap 个）后，剩余顺延到次日，依此类推；
    4. 只允许推后，不允许提前；组内各知识点的 seq 顺序与日期非递减保持。

    参数：
        grouped: 每个知识点一组的复习草案列表
        cap: 每日复习上限（必须为正整数）
    返回：
        新分组列表（组数与输入一致，组内按（日期, seq）排序）。
    """
    if cap <= 0:
        raise ValueError(f"每日复习上限必须为正整数，收到: {cap!r}")

    entries: list[tuple[int, ReviewDraft]] = [
        (group_idx, draft) for group_idx, group in enumerate(grouped) for draft in group
    ]
    entries.sort(key=lambda e: (e[1].due_date, e[0], e[1].seq))

    result: list[list[ReviewDraft]] = [[] for _ in grouped]
    placed_per_day: Counter = Counter()
    overflow: deque[tuple[int, ReviewDraft]] = deque()
    idx = 0
    total = len(entries)
    if total == 0:
        return result

    day = entries[0][1].due_date
    while idx < total or overflow:
        while idx < total and entries[idx][1].due_date <= day:
            overflow.append(entries[idx])
            idx += 1
        while overflow and placed_per_day[day] < cap:
            group_idx, draft = overflow.popleft()
            result[group_idx].append(
                ReviewDraft(seq=draft.seq, due_date=day, note=draft.note, ref_id=draft.ref_id)
            )
            placed_per_day[day] += 1
        day += timedelta(days=1)

    for group in result:
        group.sort(key=lambda d: (d.due_date, d.seq))
    return result


# ---------- 状态流转 ----------


def classify_status(due_date: date, today: date) -> str:
    """按到期日判定计划当前状态：逾期返回 ``overdue``，否则 ``pending``。"""
    return OVERDUE if due_date < today else PENDING


def transition_status(current: str, action: str) -> str:
    """复习计划状态流转。

    - 允许：pending / overdue → done | skipped（逾期补做 / 跳过）
    - 终态（done / skipped）不可再流转，抛 ValueError
    """
    if current not in TERMINAL_STATUSES | {PENDING, OVERDUE}:
        raise ValueError(f"未知状态: {current!r}")
    if action not in TERMINAL_STATUSES:
        raise ValueError(f"未知流转动作: {action!r}（应为 done/skipped）")
    if current in TERMINAL_STATUSES:
        raise ValueError(f"终态 {current!r} 不可再流转")
    return action


# ---------- 协议实现类 ----------


class ReviewSchedulerImpl:
    """实现 ``interfaces.ReviewScheduler`` 协议的遗忘曲线调度器。"""

    def build_review_schedule(
        self,
        course_tier: str,
        difficulty: int,
        first_date: date,
        daily_cap: int = 8,
    ) -> list[ReviewDraft]:
        return build_review_schedule(course_tier, difficulty, first_date, daily_cap)
