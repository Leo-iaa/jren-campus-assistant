"""自适应校准模块单元测试（纯内存分桶统计，无网络/数据库依赖）。

对齐 docs/vision.md 决策：按 课程 × 时段 × 难度 分桶，
factor = 平均(实际/预估)，默认 1.0；对齐 calibration_stats 表结构。
"""
import pytest

from backend.scheduler.calibration import CalibrationServiceImpl


def test_default_factor_is_one():
    svc = CalibrationServiceImpl()
    assert svc.factor_for(1, "morning", 3, "task") == 1.0


def test_record_single_sample():
    svc = CalibrationServiceImpl()
    svc.record(1, "morning", 3, "task", estimated_minutes=60, actual_minutes=90)
    assert svc.factor_for(1, "morning", 3, "task") == pytest.approx(1.5)


def test_factor_is_mean_of_ratios():
    svc = CalibrationServiceImpl()
    svc.record(1, "morning", 3, "task", 60, 90)  # 1.5
    svc.record(1, "morning", 3, "task", 60, 60)  # 1.0
    assert svc.factor_for(1, "morning", 3, "task") == pytest.approx(1.25)


def test_buckets_isolated_by_all_dimensions():
    svc = CalibrationServiceImpl()
    svc.record(1, "morning", 3, "task", 60, 90)  # factor 1.5
    # 任一维度不同即为独立分桶，不受影响
    assert svc.factor_for(1, "afternoon", 3, "task") == 1.0
    assert svc.factor_for(1, "morning", 4, "task") == 1.0
    assert svc.factor_for(2, "morning", 3, "task") == 1.0
    assert svc.factor_for(1, "morning", 3, "review") == 1.0
    assert svc.factor_for(None, "morning", 3, "task") == 1.0


def test_difficulty_none_is_separate_bucket():
    svc = CalibrationServiceImpl()
    svc.record(1, "morning", None, "task", 60, 120)  # 任务类无难度
    assert svc.factor_for(1, "morning", None, "task") == 2.0
    assert svc.factor_for(1, "morning", 3, "task") == 1.0


def test_course_none_bucket():
    svc = CalibrationServiceImpl()
    svc.record(None, "evening", None, "task", 30, 45)
    assert svc.factor_for(None, "evening", None, "task") == pytest.approx(1.5)


def test_review_type_bucket():
    svc = CalibrationServiceImpl()
    svc.record(1, "evening", 5, "review", 20, 40)
    assert svc.factor_for(1, "evening", 5, "review") == 2.0
    assert svc.factor_for(1, "evening", 5, "task") == 1.0


# ---------- 输入校验 ----------


def test_invalid_time_bucket_raises():
    svc = CalibrationServiceImpl()
    with pytest.raises(ValueError):
        svc.record(1, "noon", 3, "task", 60, 60)
    with pytest.raises(ValueError):
        svc.factor_for(1, "noon", 3, "task")


def test_invalid_item_type_raises():
    svc = CalibrationServiceImpl()
    with pytest.raises(ValueError):
        svc.record(1, "morning", 3, "homework", 60, 60)
    with pytest.raises(ValueError):
        svc.factor_for(1, "morning", 3, "homework")


def test_invalid_difficulty_raises():
    svc = CalibrationServiceImpl()
    for bad in (0, 6):
        with pytest.raises(ValueError):
            svc.record(1, "morning", bad, "task", 60, 60)
        with pytest.raises(ValueError):
            svc.factor_for(1, "morning", bad, "task")


def test_invalid_estimates_raise():
    svc = CalibrationServiceImpl()
    with pytest.raises(ValueError):
        svc.record(1, "morning", 3, "task", 0, 60)  # 预估必须 > 0
    with pytest.raises(ValueError):
        svc.record(1, "morning", 3, "task", -10, 60)
    with pytest.raises(ValueError):
        svc.record(1, "morning", 3, "task", 60, -1)  # 实际必须 >= 0


def test_zero_actual_allowed():
    svc = CalibrationServiceImpl()
    svc.record(1, "morning", 3, "task", 60, 0)
    assert svc.factor_for(1, "morning", 3, "task") == 0.0


# ---------- 快照（对接 calibration_stats 表） ----------


def test_snapshot_roundtrip():
    svc = CalibrationServiceImpl()
    svc.record(1, "morning", 3, "task", 60, 90)
    svc.record(2, "evening", None, "review", 30, 30)
    snap = svc.snapshot()
    assert len(snap) == 2
    row = next(r for r in snap if r["course_id"] == 1)
    assert row["sample_count"] == 1
    assert row["ratio_sum"] == pytest.approx(1.5)
    assert row["factor"] == pytest.approx(1.5)
    restored = CalibrationServiceImpl.load_snapshot(snap)
    assert restored.factor_for(1, "morning", 3, "task") == pytest.approx(1.5)
    assert restored.factor_for(2, "evening", None, "review") == 1.0
    # 未记录的分桶仍返回默认 1.0
    assert restored.factor_for(9, "morning", 3, "task") == 1.0


def test_snapshot_empty():
    assert CalibrationServiceImpl().snapshot() == []
    restored = CalibrationServiceImpl.load_snapshot([])
    assert restored.factor_for(None, "morning", None, "task") == 1.0


def test_load_snapshot_recomputes_factor_from_samples():
    # factor 由 sample_count / ratio_sum 重算，不信任快照里的 factor 字段
    snap = [
        {
            "course_id": 1,
            "time_bucket": "morning",
            "difficulty": 3,
            "item_type": "task",
            "sample_count": 2,
            "ratio_sum": 3.0,
            "factor": 99.0,  # 伪造的过期值
        }
    ]
    restored = CalibrationServiceImpl.load_snapshot(snap)
    assert restored.factor_for(1, "morning", 3, "task") == pytest.approx(1.5)
