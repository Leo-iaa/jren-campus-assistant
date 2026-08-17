"""数据模型注册入口。

导入本包即把全部 11 张表注册到 ``Base.metadata``：
settings / courses / course_sessions / knowledge_points / review_schedules /
tasks / plan_items / misc_items / data_sources / calibration_stats / plan_versions
"""
from backend.models.base import Base
from backend.models.settings import Setting
from backend.models.course import Course, CourseSession
from backend.models.knowledge import KnowledgePoint, ReviewSchedule
from backend.models.task import Task, MiscItem
from backend.models.plan import PlanItem, PlanVersion
from backend.models.datasource import DataSource
from backend.models.calibration import CalibrationStat

__all__ = [
    "Base",
    "Setting",
    "Course",
    "CourseSession",
    "KnowledgePoint",
    "ReviewSchedule",
    "Task",
    "MiscItem",
    "PlanItem",
    "PlanVersion",
    "DataSource",
    "CalibrationStat",
]
