"""用户画像学习模块单元测试（backend/scheduler/profile.py，纯逻辑）。

对齐 Issue #63 设计：
- 时段分桶：morning [0,720) / afternoon [720,1080) / evening [1080,1440)
- R1 调整偏好：14 天内同一对象 ≥3 次**跨时段**挪到同一时段 → prefer_bucket.<对象>
- R2 完成时段：14 天内同一对象 ≥3 次在同一时段完成 → fit_bucket.<对象>
- R3 夜猫线索：14 天内 ≥3 次在 21:00 后安排/完成任务 → late_worker
- add_task 事件不触发任何规则（插入时段是算法选的）
"""
from datetime import date, time

import pytest

from backend.scheduler.profile import (
    PROFILE_BUCKET_THRESHOLD,
    bucket_cn,
    bucket_of_minutes,
    bucket_of_time,
    evaluate_rules,
    subject_for,
)

TODAY = date(2026, 8, 30)

ADJUST_EVENING = {
    "event_type": "adjust",
    "occurred_at": "2026-08-24 21:30:00",
    "plan_date": "2026-08-24",
    "subject": "高等数学",
    "item_type": "task",
    "from_bucket": "afternoon",
    "to_bucket": "evening",
    "start_time": "20:00",
    "title": "高数作业",
}


def adjust(**overrides) -> dict:
    """调整事件模板（默认：高等数学 → 晚上）。"""
    event = dict(ADJUST_EVENING)
    event.update(overrides)
    return event


def done(**overrides) -> dict:
    """完成事件模板（默认：高等数学，晚上完成）。"""
    event = {
        "event_type": "done",
        "occurred_at": "2026-08-24 20:30:00",
        "plan_date": "2026-08-24",
        "subject": "高等数学",
        "item_type": "task",
        "from_bucket": None,
        "to_bucket": "evening",
        "start_time": "19:00",
        "title": "高数作业",
    }
    event.update(overrides)
    return event


# ---------- 时段分桶 ----------


def test_bucket_of_minutes_boundaries():
    assert bucket_of_minutes(0) == "morning"          # 00:00
    assert bucket_of_minutes(11 * 60 + 59) == "morning"  # 11:59
    assert bucket_of_minutes(12 * 60) == "afternoon"  # 12:00
    assert bucket_of_minutes(17 * 60 + 59) == "afternoon"  # 17:59
    assert bucket_of_minutes(18 * 60) == "evening"    # 18:00
    assert bucket_of_minutes(23 * 60 + 59) == "evening"  # 23:59


def test_bucket_of_minutes_out_of_range_raises():
    with pytest.raises(ValueError):
        bucket_of_minutes(-1)
    with pytest.raises(ValueError):
        bucket_of_minutes(1440)


def test_bucket_of_time():
    assert bucket_of_time(time(8, 0)) == "morning"
    assert bucket_of_time(time(12, 0)) == "afternoon"
    assert bucket_of_time(time(18, 0)) == "evening"


def test_bucket_cn():
    assert bucket_cn("morning") == "上午"
    assert bucket_cn("afternoon") == "下午"
    assert bucket_cn("evening") == "晚上"
    with pytest.raises(ValueError):
        bucket_cn("night")


def test_subject_for_prefers_course_name():
    assert subject_for("高等数学", "高数作业") == "高等数学"
    assert subject_for(None, "高数作业") == "高数作业"
    assert subject_for("  ", " 跑步 ") == "跑步"
    assert subject_for("", "") == "未命名"


# ---------- R1 调整偏好 ----------


def test_r1_three_cross_bucket_adjusts_learn_prefer():
    events = [adjust(occurred_at=f"2026-08-2{i} 21:00:00") for i in range(1, 4)]
    rules = evaluate_rules(events, TODAY)
    assert [r.feature_key for r in rules] == ["prefer_bucket.高等数学"]
    rule = rules[0]
    assert rule.feature_type == "prefer_bucket"
    assert rule.value == "evening"
    assert rule.confidence == 3
    assert "2026-08-21" in rule.evidence and "2026-08-23" in rule.evidence
    assert "3 次" in rule.evidence and "高数作业" in rule.evidence  # 证据用条目标题
    assert "晚上" in rule.evidence  # 中文时段名


def test_r1_two_adjusts_not_enough():
    events = [adjust(occurred_at=f"2026-08-2{i} 21:00:00") for i in range(1, 3)]
    assert evaluate_rules(events, TODAY) == []


def test_r1_threshold_boundary_is_exclusive():
    # 恰好 PROFILE_BUCKET_THRESHOLD - 1 次不触发，达到阈值触发
    below = [adjust(occurred_at=f"2026-08-2{i} 21:00:00") for i in range(1, PROFILE_BUCKET_THRESHOLD)]
    assert evaluate_rules(below, TODAY) == []
    at = below + [adjust(occurred_at="2026-08-24 21:00:00")]
    assert len(evaluate_rules(at, TODAY)) == 1


def test_r1_same_bucket_micro_adjust_not_counted():
    # 19:00→20:00 都是晚上，不算「挪时段」信号
    events = [
        adjust(occurred_at=f"2026-08-2{i} 21:00:00", from_bucket="evening") for i in range(1, 4)
    ]
    assert evaluate_rules(events, TODAY) == []


def test_r1_mixed_target_buckets_not_counted_together():
    events = [
        adjust(occurred_at="2026-08-21 21:00:00", to_bucket="evening"),
        adjust(occurred_at="2026-08-22 21:00:00", to_bucket="evening"),
        adjust(
            occurred_at="2026-08-23 21:00:00",
            to_bucket="afternoon",
            from_bucket="morning",
        ),
    ]
    rules = evaluate_rules(events, TODAY)
    # 同一目标时段只有 2 次 → 不学习；不同目标不合并
    assert rules == []


def test_r1_different_subjects_not_mixed():
    events = [
        adjust(occurred_at="2026-08-21 21:00:00", subject="高等数学"),
        adjust(occurred_at="2026-08-22 21:00:00", subject="大学英语"),
        adjust(occurred_at="2026-08-23 21:00:00", subject="高等数学"),
        adjust(occurred_at="2026-08-24 21:00:00", subject="高等数学"),
    ]
    rules = evaluate_rules(events, TODAY)
    assert [r.feature_key for r in rules] == ["prefer_bucket.高等数学"]
    assert rules[0].confidence == 3  # 大学英语只有 1 次，不计入


def test_r1_events_outside_window_ignored():
    events = [
        adjust(occurred_at="2026-08-10 21:00:00"),  # 窗口外（>14 天前）
        adjust(occurred_at="2026-08-11 21:00:00"),
        adjust(occurred_at="2026-08-24 21:00:00"),
    ]
    assert evaluate_rules(events, TODAY) == []  # 窗口内只有 1 次


def test_r1_window_edge_inclusive():
    # 恰好 14 天前（08-16）仍在窗口内
    events = [
        adjust(occurred_at="2026-08-16 21:00:00"),
        adjust(occurred_at="2026-08-17 21:00:00"),
        adjust(occurred_at="2026-08-24 21:00:00"),
    ]
    assert len(evaluate_rules(events, TODAY)) == 1


def test_r1_learns_fit_from_misc_title():
    events = [
        adjust(
            occurred_at=f"2026-08-2{i} 21:00:00",
            subject="跑步",
            item_type="misc",
            title="跑步",
        )
        for i in range(1, 4)
    ]
    rules = evaluate_rules(events, TODAY)
    assert [r.feature_key for r in rules] == ["prefer_bucket.跑步"]
    assert rules[0].value == "evening"


# ---------- R2 完成时段 ----------


def test_r2_three_dones_same_bucket_learn_fit():
    events = [done(occurred_at=f"2026-08-2{i} 20:00:00") for i in range(1, 4)]
    rules = evaluate_rules(events, TODAY)
    assert [r.feature_key for r in rules] == ["fit_bucket.高等数学"]
    rule = rules[0]
    assert rule.value == "evening"
    assert rule.confidence == 3
    assert "晚上完成" in rule.evidence


def test_r2_two_dones_not_enough():
    events = [done(occurred_at=f"2026-08-2{i} 20:00:00") for i in range(1, 3)]
    assert evaluate_rules(events, TODAY) == []


def test_r2_dones_in_different_buckets_not_counted():
    events = [
        done(occurred_at="2026-08-21 20:00:00", to_bucket="evening"),
        done(occurred_at="2026-08-22 20:00:00", to_bucket="evening"),
        done(occurred_at="2026-08-23 20:00:00", to_bucket="morning"),
    ]
    assert evaluate_rules(events, TODAY) == []


# ---------- R3 夜猫线索 ----------


def test_r3_three_late_activities_learn_late_worker():
    events = [
        adjust(occurred_at="2026-08-21 22:00:00", start_time="21:30"),
        done(occurred_at="2026-08-22 21:30:00", start_time="21:00"),
        adjust(occurred_at="2026-08-23 23:00:00", start_time="22:30"),
    ]
    rules = evaluate_rules(events, TODAY)
    late = [r for r in rules if r.feature_key == "late_worker"]
    assert len(late) == 1
    assert late[0].value == "true"
    assert late[0].confidence == 3
    assert "21:00 后" in late[0].evidence


def test_r3_mixed_with_early_activities():
    # 3 次晚间 + 多次白天：晚间计数不变，仍学习
    events = [
        adjust(occurred_at="2026-08-21 22:00:00", start_time="21:30"),
        done(occurred_at="2026-08-22 21:30:00", start_time="21:00"),
        adjust(occurred_at="2026-08-23 23:00:00", start_time="22:30"),
        done(occurred_at="2026-08-24 09:00:00", start_time="08:30"),
    ]
    late = [r for r in evaluate_rules(events, TODAY) if r.feature_key == "late_worker"]
    assert len(late) == 1 and late[0].confidence == 3


def test_r3_activity_at_exactly_2100_counts():
    events = [
        adjust(occurred_at="2026-08-21 21:00:00", start_time="21:00"),
        done(occurred_at="2026-08-22 21:00:00", start_time="21:00"),
        adjust(occurred_at="2026-08-23 21:00:00", start_time="21:00"),
    ]
    late = [r for r in evaluate_rules(events, TODAY) if r.feature_key == "late_worker"]
    assert len(late) == 1


# ---------- 事件类型与规则组合 ----------


def test_add_task_events_never_trigger_rules():
    # 新增任务 3 次落在晚上 → 不学习（插入时段是算法选的，不是用户偏好）
    events = [
        {
            "event_type": "add_task",
            "occurred_at": f"2026-08-2{i} 21:00:00",
            "plan_date": f"2026-08-2{i}",
            "subject": "高等数学",
            "item_type": "task",
            "from_bucket": None,
            "to_bucket": "evening",
            "start_time": "19:00",
            "title": "高数作业",
        }
        for i in range(1, 4)
    ]
    assert evaluate_rules(events, TODAY) == []


def test_r1_and_r2_and_r3_combine():
    events = [
        adjust(occurred_at="2026-08-21 22:00:00", start_time="21:30"),
        adjust(occurred_at="2026-08-22 22:00:00", start_time="21:30"),
        adjust(occurred_at="2026-08-23 22:00:00", start_time="21:30"),
        done(occurred_at="2026-08-21 20:00:00"),
        done(occurred_at="2026-08-22 20:00:00"),
        done(occurred_at="2026-08-23 20:00:00"),
    ]
    rules = evaluate_rules(events, TODAY)
    keys = [r.feature_key for r in rules]
    assert keys == ["fit_bucket.高等数学", "late_worker", "prefer_bucket.高等数学"]


def test_events_with_bad_fields_skipped():
    events = [
        adjust(occurred_at="不是日期", to_bucket="evening"),
        adjust(occurred_at="2026-08-22 21:00:00", to_bucket="evening"),
        adjust(occurred_at="2026-08-23 21:00:00", to_bucket="evening"),
        adjust(occurred_at="2026-08-24 21:00:00", to_bucket="weird"),
        adjust(occurred_at="2026-08-25 21:00:00", to_bucket="evening"),
    ]
    rules = evaluate_rules(events, TODAY)
    assert [r.feature_key for r in rules] == ["prefer_bucket.高等数学"]
    assert rules[0].confidence == 3  # 非法日期与非法时段不计入


def test_rules_sorted_deterministically():
    events = [
        adjust(occurred_at=f"2026-08-2{i} 22:00:00", subject="高等数学", start_time="21:30")
        for i in range(1, 4)
    ] + [
        done(occurred_at=f"2026-08-2{i} 20:00:00", subject="大学英语") for i in range(1, 4)
    ]
    keys = [r.feature_key for r in evaluate_rules(events, TODAY)]
    assert keys == sorted(keys)
