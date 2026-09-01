"""跑步训练计划规则引擎测试（纯逻辑，确定性输出）。"""
from __future__ import annotations

from backend.mcp_client.coros import RunningActivity, RunningSnapshot
from backend.scheduler.running_plan import (
    EASY,
    INTERVAL,
    LONG_RUN,
    REST,
    TEMPO,
    generate_week_plan,
    weekly_distance_km,
)


def _activities(*, days=7, km_per_run=5.0, pace=330, workout="easy run", start="2026-08-24"):
    from datetime import date, timedelta

    d0 = date.fromisoformat(start)
    return [
        RunningActivity(
            date=(d0 + timedelta(days=i)).isoformat(),
            distance_km=km_per_run,
            duration_minutes=30,
            pace_sec_per_km=pace,
            workout_type=workout,
        )
        for i in range(days)
    ]


# ---------- 周跑量 ----------


def test_weekly_distance_sums_last_7_days():
    acts = _activities(days=10, km_per_run=5.0)  # 10 天各 5km
    total = weekly_distance_km(acts, end_date="2026-08-30")
    assert total == 35.0  # 只有近 7 天计入


def test_weekly_distance_empty():
    assert weekly_distance_km([]) is None


# ---------- 周计划生成 ----------


def test_plan_normal_week_increases_10_percent():
    snap = RunningSnapshot(
        activities=_activities(),
        recovery={"recoveryLevel": "good"},
        load={"loadRatio": 1.1},
        fitness={"vo2Max": 52},
    )
    # end_date 与 _activities 的固定日期窗对齐（weekly_distance_km 默认用真实今天，
    # 模拟数据会随真实日期推移滑出 7 天窗口 → 必须显式锚定）
    plan = generate_week_plan(snap, today_iso="2026-08-30", end_date="2026-08-30")
    assert plan.weekly_distance_km == 38.5  # 35 × 1.1
    kinds = [s.kind for s in plan.sessions]
    assert EASY in kinds and LONG_RUN in kinds
    assert INTERVAL in kinds  # 恢复好 + 负荷正常 → 有强度课
    # 理由引用真实数据
    assert any("35.0" in r for r in plan.rationale)
    assert any("38.5" in r for r in plan.rationale)


def test_plan_poor_recovery_reduces_load():
    snap = RunningSnapshot(
        activities=_activities(),
        recovery={"recoveryLevel": "poor"},
        load={"loadRatio": 1.4},
    )
    plan = generate_week_plan(snap, today_iso="2026-08-30", end_date="2026-08-30")
    assert plan.weekly_distance_km == 24.5  # 35 × 0.7 减量
    kinds = [s.kind for s in plan.sessions]
    assert INTERVAL not in kinds and TEMPO not in kinds  # 恢复差不排强度
    assert any("减量" in r for r in plan.rationale)


def test_plan_high_load_ratio_caps_frequency():
    snap = RunningSnapshot(
        activities=_activities(),
        recovery={"recoveryLevel": "moderate"},
        load={"loadRatio": 1.6},  # 负荷比 >1.5 → 每周 2 次
    )
    plan = generate_week_plan(snap, today_iso="2026-08-30")
    assert len(plan.sessions) <= 2
    assert all(s.kind in (EASY, REST) for s in plan.sessions)


def test_plan_good_recovery_low_load_swaps_interval_to_tempo():
    snap = RunningSnapshot(
        activities=_activities(),
        recovery={"recoveryLevel": "good"},
        load={"loadRatio": 0.9},
    )
    plan = generate_week_plan(snap, today_iso="2026-08-30")
    kinds = [s.kind for s in plan.sessions]
    assert TEMPO in kinds and INTERVAL not in kinds
    assert any("节奏跑" in r for r in plan.rationale)


def test_plan_no_data_conservative_start():
    snap = RunningSnapshot(activities=[])
    plan = generate_week_plan(snap, today_iso="2026-08-30")
    assert plan.weekly_distance_km == 15.0
    assert plan.warnings  # 提示无数据
    assert len(plan.sessions) == 3  # 15km → 每周 3 次


def test_plan_deterministic():
    snap = RunningSnapshot(
        activities=_activities(),
        recovery={"recoveryLevel": "good"},
        load={"loadRatio": 1.1},
    )
    a = generate_week_plan(snap, today_iso="2026-08-30")
    b = generate_week_plan(snap, today_iso="2026-08-30")
    assert a == b


def test_plan_intensity_not_on_consecutive_days():
    """强度课与长距离不连续排（骨架保证中间至少隔 1 天）。"""
    snap = RunningSnapshot(
        activities=_activities(),
        recovery={"recoveryLevel": "good"},
        load={"loadRatio": 1.1},
    )
    plan = generate_week_plan(snap, today_iso="2026-08-30")
    hard_offsets = [s.day_offset for s in plan.sessions if s.kind in (INTERVAL, TEMPO, LONG_RUN)]
    for prev, cur in zip(hard_offsets, hard_offsets[1:]):
        assert cur - prev >= 2  # 强度课之间 ≥2 天间隔


def test_plan_details_reference_avg_pace():
    snap = RunningSnapshot(
        activities=_activities(pace=330),
        recovery={"recoveryLevel": "good"},
        load={"loadRatio": 1.1},
    )
    plan = generate_week_plan(snap, today_iso="2026-08-30")
    easy = next(s for s in plan.sessions if s.kind == EASY)
    assert "6'15\"" in easy.detail  # 330+45=375s = 6'15"/km
