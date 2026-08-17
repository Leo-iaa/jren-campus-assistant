"""遗忘曲线调度与时间表规划模块。

算法实现（纯 Python，不依赖 FastAPI / 数据库）：
- :mod:`backend.scheduler.review`：遗忘曲线复习调度器（档位序列 / 难度微调 / 每日上限 / 状态流转）
- :mod:`backend.scheduler.planner`：时间表规划器（贪心约束求解 / 释放时段 / 学习偏好 / dropped 报告）
- :mod:`backend.scheduler.calibration`：自适应校准（课程 × 时段 × 难度 分桶修正系数）

接口契约见 :mod:`backend.scheduler.interfaces`。
"""
from backend.scheduler.calibration import CalibrationServiceImpl
from backend.scheduler.interfaces import PlanItemDraft, ReviewDraft
from backend.scheduler.planner import PlanBuilderImpl, PlanResult, build_plan, build_plan_full
from backend.scheduler.review import (
    ReviewRequest,
    ReviewSchedulerImpl,
    apply_daily_cap,
    build_review_schedule,
    build_schedule_with_cap,
    classify_status,
    transition_status,
)

__all__ = [
    # 数据结构
    "ReviewDraft",
    "PlanItemDraft",
    "PlanResult",
    "ReviewRequest",
    # 遗忘曲线调度
    "ReviewSchedulerImpl",
    "build_review_schedule",
    "build_schedule_with_cap",
    "apply_daily_cap",
    "classify_status",
    "transition_status",
    # 时间表规划
    "PlanBuilderImpl",
    "build_plan",
    "build_plan_full",
    # 自适应校准
    "CalibrationServiceImpl",
]
