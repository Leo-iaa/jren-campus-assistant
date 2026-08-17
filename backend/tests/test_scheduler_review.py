"""遗忘曲线调度器单元测试（纯逻辑，无网络/数据库依赖）。

对齐 docs/vision.md 定稿决策：
- 档位序列：S/A = 当晚+1/2/4/7/15；B = 当晚+1/7；C 不复习
- 难度微调：≥4 首次复习提前至课后 2 小时（同日，note 标注）；≤2 跳过当晚
- S 档难度≥4：额外增加一次（插在第 2 天与第 4 天之间）
- 每日上限：批量生成时超出顺延次日（FIFO）
- 状态流转：pending/overdue → done/skipped；终态不可再流转
"""
from collections import Counter
from datetime import date

import pytest

from backend.scheduler.interfaces import ReviewDraft
from backend.scheduler.review import (
    ReviewSchedulerImpl,
    apply_daily_cap,
    build_review_schedule,
    classify_status,
    transition_status,
)

D0 = date(2026, 9, 7)  # 周一（示例开课日）


def _offsets(drafts, base=D0):
    return [(d.due_date - base).days for d in drafts]


# ---------- 档位序列 ----------


def test_s_tier_standard_sequence():
    drafts = build_review_schedule("S", 3, D0)
    assert [d.seq for d in drafts] == [1, 2, 3, 4, 5, 6]
    assert _offsets(drafts) == [0, 1, 2, 4, 7, 15]


def test_a_tier_same_as_s():
    assert _offsets(build_review_schedule("A", 3, D0)) == [0, 1, 2, 4, 7, 15]


def test_b_tier_sequence():
    drafts = build_review_schedule("B", 3, D0)
    assert [d.seq for d in drafts] == [1, 2, 3]
    assert _offsets(drafts) == [0, 1, 7]


def test_c_tier_no_reviews():
    assert build_review_schedule("C", 3, D0) == []
    assert build_review_schedule("C", 5, D0) == []  # 难度再高也不复习


# ---------- 难度微调 ----------


def test_s_tier_hard_extra_review():
    drafts = build_review_schedule("S", 4, D0)
    assert _offsets(drafts) == [0, 1, 2, 3, 4, 7, 15]  # 额外一次在第 3 天
    assert len(drafts) == 7
    extra = [d for d in drafts if (d.due_date - D0).days == 3]
    assert len(extra) == 1
    assert "额外" in extra[0].note


def test_a_tier_hard_no_extra():
    # 额外一次仅 S 档享有
    assert _offsets(build_review_schedule("A", 5, D0)) == [0, 1, 2, 4, 7, 15]


def test_hard_first_review_advanced_note():
    drafts = build_review_schedule("A", 5, D0)
    first = drafts[0]
    assert first.due_date == D0  # 日期不变（上课当天），只是提前到课后 2 小时
    assert "2 小时" in first.note
    assert "难度" in first.note


def test_easy_skips_evening_review():
    for tier, expected in [("S", [1, 2, 4, 7, 15]), ("A", [1, 2, 4, 7, 15]), ("B", [1, 7])]:
        assert _offsets(build_review_schedule(tier, 2, D0)) == expected
        assert _offsets(build_review_schedule(tier, 1, D0)) == expected


def test_difficulty_three_keeps_evening():
    assert 0 in _offsets(build_review_schedule("A", 3, D0))


def test_s_hard_and_easy_not_combined():
    # S 档难度≤2：跳过当晚，也不触发「额外一次」
    assert _offsets(build_review_schedule("S", 2, D0)) == [1, 2, 4, 7, 15]


# ---------- 输入校验 ----------


def test_invalid_tier_raises():
    with pytest.raises(ValueError):
        build_review_schedule("D", 3, D0)


def test_invalid_difficulty_raises():
    for bad in (0, 6):
        with pytest.raises(ValueError):
            build_review_schedule("A", bad, D0)


def test_single_kp_ignores_daily_cap():
    # 单个知识点自身序列每天至多一次复习，cap 不改变序列
    assert len(build_review_schedule("S", 3, D0, daily_cap=1)) == 6


# ---------- 每日复习上限（批量顺延） ----------


def test_apply_daily_cap_respects_limit():
    # 3 个 S 档知识点同日开课，cap=2：每一天最多 2 个复习
    grouped = [build_review_schedule("S", 3, D0) for _ in range(3)]
    result = apply_daily_cap(grouped, cap=2)
    flat = [d for g in result for d in g]
    assert len(flat) == 18  # 总数不变
    counts = Counter(d.due_date for d in flat)
    assert all(c <= 2 for c in counts.values())


def test_apply_daily_cap_deferral_only_forward():
    # 顺延只允许推后，不允许提前
    grouped = [build_review_schedule("S", 3, D0) for _ in range(3)]
    result = apply_daily_cap(grouped, cap=2)
    for new_group, orig_group in zip(result, grouped):
        for new_draft, old_draft in zip(new_group, orig_group):
            assert new_draft.due_date >= old_draft.due_date


def test_apply_daily_cap_preserves_kp_order():
    # 每个知识点内部按 seq 顺序、日期非递减
    grouped = [build_review_schedule("S", 3, D0) for _ in range(3)]
    result = apply_daily_cap(grouped, cap=2)
    for g in result:
        dates = [d.due_date for d in g]
        assert dates == sorted(dates)
        assert [d.seq for d in g] == [1, 2, 3, 4, 5, 6]


def test_apply_daily_cap_same_day_cap_overflow_lands_next_day():
    # cap=1、2 个知识点：第 0 天只有 1 个复习，另一个顺延到第 1 天
    grouped = [build_review_schedule("A", 3, D0) for _ in range(2)]
    result = apply_daily_cap(grouped, cap=1)
    flat = sorted(d.due_date for d in result[0])  # 只看第一个知识点
    assert flat[0] == D0


def test_apply_daily_cap_invalid_cap():
    with pytest.raises(ValueError):
        apply_daily_cap([], cap=0)


def test_apply_daily_cap_empty_input():
    assert apply_daily_cap([], cap=8) == []


# ---------- 状态流转（跳过 / 逾期） ----------


def test_classify_status_overdue():
    assert classify_status(D0, date(2026, 9, 8)) == "overdue"
    assert classify_status(D0, D0) == "pending"  # 当天未完成仍是 pending
    assert classify_status(D0, date(2026, 9, 6)) == "pending"


def test_transition_status_ok():
    assert transition_status("pending", "done") == "done"
    assert transition_status("pending", "skipped") == "skipped"
    assert transition_status("overdue", "done") == "done"  # 逾期补做
    assert transition_status("overdue", "skipped") == "skipped"


def test_transition_terminal_state_rejected():
    for terminal in ("done", "skipped"):
        with pytest.raises(ValueError):
            transition_status(terminal, "done")
        with pytest.raises(ValueError):
            transition_status(terminal, "skipped")


def test_transition_unknown_inputs():
    with pytest.raises(ValueError):
        transition_status("wat", "done")
    with pytest.raises(ValueError):
        transition_status("pending", "wat")


# ---------- 协议实现类 ----------


def test_impl_class_matches_protocol():
    impl = ReviewSchedulerImpl()
    drafts = impl.build_review_schedule("B", 3, D0)
    assert all(isinstance(d, ReviewDraft) for d in drafts)
    assert _offsets(drafts) == [0, 1, 7]
