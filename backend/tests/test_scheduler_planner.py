"""时间表规划器单元测试（纯逻辑，无网络/数据库依赖）。

对齐 docs/vision.md 与 docs/database.md 设计决策：
- 固定课程块为硬屏障（不可重叠）；B/C 档 `release_slot=True` 的时段可安排其他任务
- 复习/作业优先落入学习时段偏好窗口，溢出到其余空闲时段
- 输出保证 UNIQUE(date, start_time)：与课程起始分钟错开、彼此不重复
- 放不下的任务进入 dropped 报告（硬保证：不产生冲突）
"""
from datetime import date, time

import pytest

from backend.scheduler.interfaces import PlanItemDraft
from backend.scheduler.planner import PlanBuilderImpl, build_plan, build_plan_full

D = date(2026, 9, 7)


def course(start, end, release=False, title="高数"):
    return PlanItemDraft(
        date=D, start=start, end=end, item_type="course", ref_id=1, title=title, release_slot=release
    )


def item(start, end, item_type="task", title="作业", ref_id=1):
    return PlanItemDraft(date=D, start=start, end=end, item_type=item_type, ref_id=ref_id, title=title)


# ---------- 固定课程块 ----------


def test_courses_kept_unchanged():
    cs = [course(time(8, 0), time(9, 0)), course(time(10, 0), time(11, 0))]
    out = build_plan(D, cs, [], [], [])
    assert [(p.start, p.end) for p in out] == [(time(8, 0), time(9, 0)), (time(10, 0), time(11, 0))]
    assert all(p.item_type == "course" for p in out)
    assert all(p.date == D for p in out)


def test_overlapping_hard_courses_raise():
    with pytest.raises(ValueError):
        build_plan(D, [course(time(8, 0), time(10, 0)), course(time(9, 0), time(11, 0))], [], [], [])


def test_duplicate_course_start_raises():
    # 同一起始分钟会破坏 UNIQUE(date, start_time)，直接拒绝
    with pytest.raises(ValueError):
        build_plan(
            D,
            [course(time(8, 0), time(9, 0)), course(time(8, 0), time(10, 0), title="另一门")],
            [],
            [],
            [],
        )


def test_invalid_course_duration_raises():
    with pytest.raises(ValueError):
        build_plan(D, [course(time(9, 0), time(9, 0))], [], [], [])  # 零时长课程


# ---------- 任务放置 ----------


def test_task_fills_gap_after_course():
    out = build_plan(D, [course(time(8, 0), time(9, 0))], [item(time(0, 0), time(0, 30))], [], [])
    task = [p for p in out if p.item_type == "task"][0]
    assert (task.start, task.end) == (time(9, 0), time(9, 30))


def test_duration_taken_from_draft():
    # 时长取自输入草案的 end - start（45 分钟），与输入起始时刻无关
    out = build_plan(D, [course(time(8, 0), time(9, 0))], [item(time(12, 0), time(12, 45), title="45分钟作业")], [], [])
    task = [p for p in out if p.item_type == "task"][0]
    assert (task.start, task.end) == (time(9, 0), time(9, 45))


def test_no_overlap_between_all_items():
    cs = [course(time(8, 0), time(9, 0)), course(time(13, 0), time(14, 0))]
    tasks = [item(time(0, 0), time(0, 45)) for _ in range(3)]
    out = build_plan(D, cs, tasks, [], [])
    blocks = sorted((p.start, p.end) for p in out)
    for (s1, e1), (s2, e2) in zip(blocks, blocks[1:]):
        assert e1 <= s2  # 半开区间不重叠


def test_invalid_duration_raises():
    with pytest.raises(ValueError):
        build_plan(D, [], [item(time(9, 0), time(9, 0))], [], [])  # 零时长
    with pytest.raises(ValueError):
        build_plan(D, [], [item(time(10, 0), time(9, 0))], [], [])  # 负时长


def test_invalid_item_type_raises():
    with pytest.raises(ValueError):
        build_plan(D, [], [item(time(0, 0), time(0, 30), item_type="homework")], [], [])


def test_invalid_study_hours_raises():
    with pytest.raises(ValueError):
        build_plan(D, [], [], [], [], study_hours=(time(21, 0), time(19, 0)))


# ---------- 学习时段偏好 ----------


def test_review_prefers_study_hours():
    cs = [course(time(8, 0), time(12, 0))]
    reviews = [item(time(0, 0), time(0, 30), item_type="review", title="复习1")]
    out = build_plan(D, cs, [], reviews, [], study_hours=(time(19, 0), time(21, 0)))
    review = [p for p in out if p.item_type == "review"][0]
    assert (review.start, review.end) == (time(19, 0), time(19, 30))


def test_task_prefers_study_hours():
    cs = [course(time(8, 0), time(12, 0))]
    tasks = [item(time(0, 0), time(1, 0), title="作业1")]
    out = build_plan(D, cs, tasks, [], [], study_hours=(time(19, 0), time(21, 0)))
    task = [p for p in out if p.item_type == "task"][0]
    assert task.start == time(19, 0)


def test_task_spills_outside_study_hours_when_full():
    # 学习时段被课程占满 → 任务顺延到其余空闲时段（最早适配）
    cs = [course(time(19, 0), time(21, 0))]
    tasks = [item(time(0, 0), time(1, 0), title="作业1")]
    out = build_plan(D, cs, tasks, [], [], study_hours=(time(19, 0), time(21, 0)))
    task = [p for p in out if p.item_type == "task"][0]
    assert task.start == time(8, 0)  # 08:00-19:00 空闲 → 最早空闲时段


def test_review_priority_over_task_in_study_window():
    # 学习时段 19:00-20:30 被课程占掉 19:00-20:00，只剩 30 分钟 → 复习优先占窗口
    cs = [course(time(19, 0), time(20, 0))]
    reviews = [item(time(0, 0), time(0, 30), item_type="review", title="复习A")]
    tasks = [item(time(0, 0), time(0, 30), title="作业A")]
    out = build_plan(D, cs, tasks, reviews, [], study_hours=(time(19, 0), time(20, 30)))
    placed = {(p.item_type, p.start): p for p in out if p.item_type != "course"}
    assert placed[("review", time(20, 0))].title == "复习A"
    task = [p for p in out if p.item_type == "task"][0]
    assert task.start == time(8, 0)  # 溢出到学习时段之外


# ---------- 释放时段（B/C 档） ----------


def test_released_course_slot_is_available():
    released = course(time(8, 0), time(10, 0), release=True, title="水课")
    hard = course(time(10, 0), time(12, 0), title="专业课")
    tasks = [item(time(0, 0), time(1, 0), title="作业1")]
    out = build_plan(D, [released, hard], tasks, [], [])
    task = [p for p in out if p.item_type == "task"][0]
    assert time(8, 0) <= task.start and task.end <= time(10, 0)  # 落在释放时段内
    assert len([p for p in out if p.item_type == "course"]) == 2  # 课程仍在输出


def test_released_slot_avoids_same_start_minute():
    # 与课程 08:00 错开起始分钟，保证 UNIQUE(date, start_time)
    released = course(time(8, 0), time(10, 0), release=True)
    tasks = [item(time(0, 0), time(1, 0), title="作业1")]
    out = build_plan(D, [released], tasks, [], [])
    task = [p for p in out if p.item_type == "task"][0]
    assert task.start == time(8, 1)
    starts = [p.start for p in out]
    assert len(set(starts)) == len(starts)


def test_hard_course_not_overlapped_by_task():
    hard = course(time(8, 0), time(10, 0), title="专业课")
    tasks = [item(time(0, 0), time(1, 0), title="作业1")]
    out = build_plan(D, [hard], tasks, [], [])
    task = [p for p in out if p.item_type == "task"][0]
    assert task.start >= time(10, 0)  # 只能在课程结束后


# ---------- 整体性质 ----------


def test_all_output_sorted_and_unique_starts():
    cs = [course(time(14, 0), time(15, 0)), course(time(8, 0), time(9, 0))]
    tasks = [item(time(0, 0), time(0, 40), title="作业B"), item(time(0, 0), time(1, 0), title="作业A")]
    reviews = [item(time(0, 0), time(0, 20), item_type="review", title="复习X")]
    miscs = [item(time(0, 0), time(0, 15), item_type="misc", title="取快递")]
    out = build_plan(D, cs, tasks, reviews, miscs)
    starts = [p.start for p in out]
    assert starts == sorted(starts)  # 按时间排序
    assert len(set(starts)) == len(starts)  # UNIQUE(date, start_time)
    assert all(p.date == D for p in out)


def test_dropped_items_reported():
    # 全天被硬课程占满 → 任务放不下 → 进入 dropped，不产生冲突
    cs = [course(time(8, 0), time(22, 0))]
    tasks = [item(time(0, 0), time(1, 0), title="放不下的作业")]
    result = build_plan_full(D, cs, tasks, [], [])
    assert result.placed == cs
    assert [d.title for d in result.dropped] == ["放不下的作业"]


def test_misc_placed_after_study_items():
    # 杂项优先级最低：复习/作业先占用最早空闲，杂项随后填
    cs = [course(time(8, 0), time(9, 0))]
    reviews = [item(time(0, 0), time(0, 30), item_type="review", title="复习X")]
    miscs = [item(time(0, 0), time(0, 15), item_type="misc", title="取快递")]
    out = build_plan(D, cs, [], reviews, miscs)
    review = next(p for p in out if p.item_type == "review")
    misc = next(p for p in out if p.item_type == "misc")
    assert (review.start, review.end) == (time(9, 0), time(9, 30))
    assert (misc.start, misc.end) == (time(9, 30), time(9, 45))


def test_impl_class_matches_protocol():
    impl = PlanBuilderImpl()
    cs = [course(time(8, 0), time(9, 0))]
    out = impl.build_plan(D, cs, [item(time(0, 0), time(0, 30))], [], [])
    assert all(isinstance(p, PlanItemDraft) for p in out)
    assert len(out) == 2
