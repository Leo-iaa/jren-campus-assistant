"""自适应校准分桶统计。

对应 docs/database.md 3.10 ``calibration_stats``。
只存聚合统计（样本数 + 修正系数），不存明细，保持简单。
"""
from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class CalibrationStat(Base):
    """课程 × 时段 × 难度 分桶校准：factor = ratio_sum / sample_count。"""

    __tablename__ = "calibration_stats"
    __table_args__ = (
        UniqueConstraint("course_id", "time_bucket", "difficulty", "item_type", name="uq_calib_bucket"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"))
    time_bucket: Mapped[str | None] = mapped_column(String)  # 'morning' | 'afternoon' | 'evening'
    difficulty: Mapped[int | None] = mapped_column(Integer)  # 1-5 或 NULL（任务类）
    item_type: Mapped[str] = mapped_column(String, nullable=False)  # 'task' | 'review'
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    ratio_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")

    def __repr__(self) -> str:
        return f"<CalibrationStat id={self.id} course={self.course_id} bucket={self.time_bucket} factor={self.factor}>"
