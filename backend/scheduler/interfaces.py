"""调度器 / 规划器 / 校准器的接口签名（占位，待算法会话实现）。

设计依据 docs/architecture.md 2.4/2.5/2.6：
- 遗忘曲线调度器：按课程档位 + 知识点难度生成复习序列
- 时间表规划器：融合课程 / 作业 / 复习 / 杂项，生成不冲突的时间表
- 自适应校准模块：按 课程 × 时段 × 难度 分桶修正耗时预估

实现约定：
- 实现类应放在 ``backend/scheduler/`` 下（如 ``scheduler/review.py``、``scheduler/planner.py``）
- 接口返回类型为纯数据结构（dataclass / dict），不依赖 ORM 对象
"""
from dataclasses import dataclass
from datetime import date, time
from typing import Protocol

# ---------- 公共数据结构 ----------


@dataclass(frozen=True)
class ReviewDraft:
    """单个复习点的草案（由遗忘曲线调度器产出）。"""

    seq: int  # 第几次复习（1,2,3...）
    due_date: date  # 计划复习日期
    note: str = ""  # 生成说明（如「难度≥4 提前至课后 2 小时」）
    ref_id: int | None = None  # 关联知识点 id（批量生成时填充，供落库映射）


@dataclass(frozen=True)
class PlanItemDraft:
    """时间表规划器产出的单个计划项草案。"""

    date: date
    start: time
    end: time
    item_type: str  # course / task / review / misc
    ref_id: int | None
    title: str
    release_slot: bool = False  # 课程块是否释放（B/C 档：该时段可安排其他任务）


# ---------- 接口签名（占位） ----------


class ReviewScheduler(Protocol):
    """遗忘曲线复习调度器。

    输入知识点（所属课程档位 + 难度）与首次复习日期，
    输出该知识点的全部复习点序列。
    """

    def build_review_schedule(
        self,
        course_tier: str,  # 'S' | 'A' | 'B' | 'C'
        difficulty: int,  # 1-5
        first_date: date,  # 首次复习日期（通常为上课当天）
        daily_cap: int = 8,  # 每日复习上限（超出顺延次日）
    ) -> list[ReviewDraft]:
        """生成复习点序列。"""
        ...


class PlanBuilder(Protocol):
    """时间表规划器。

    输入某天的固定占用（课表）与可变任务（作业/复习/杂项），
    输出不冲突的按时间排序计划项草案。
    """

    def build_plan(
        self,
        plan_date: date,
        course_sessions: list[PlanItemDraft],
        tasks: list[PlanItemDraft],
        reviews: list[PlanItemDraft],
        misc_items: list[PlanItemDraft],
        study_hours: tuple[time, time] | None = None,
    ) -> list[PlanItemDraft]:
        """生成当日建议时间表（约束求解，保证不冲突）。"""
        ...


class CalibrationService(Protocol):
    """习惯自适应校准器：维护「预估 vs 实际」分桶统计并给出修正系数。"""

    def record(
        self,
        course_id: int | None,
        time_bucket: str,  # 'morning' | 'afternoon' | 'evening'
        difficulty: int | None,  # 1-5 或 None（任务类）
        item_type: str,  # 'task' | 'review'
        estimated_minutes: int,
        actual_minutes: int,
    ) -> None:
        """记录一次完成情况，更新对应分桶的修正系数。"""
        ...

    def factor_for(
        self,
        course_id: int | None,
        time_bucket: str,
        difficulty: int | None,
        item_type: str,
    ) -> float:
        """查询某分桶的耗时修正系数（默认 1.0）。"""
        ...
