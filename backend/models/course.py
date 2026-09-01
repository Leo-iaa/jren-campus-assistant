"""课程与课程时间块。

对应 docs/database.md 3.2 ``courses`` 与 3.3 ``course_sessions``。
"""
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, shanghai_now

# 课程档位（产品决策：S/A/B/C，见 docs/vision.md）
COURSE_TIERS = ("S", "A", "B", "C")


class Course(Base):
    """课程：档位制复习策略的主体（tier 用户可自设）。"""

    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("tier IN ('S','A','B','C')", name="ck_courses_tier"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str | None] = mapped_column(String)
    tier: Mapped[str] = mapped_column(String, nullable=False, default="A", server_default="A")
    color: Mapped[str | None] = mapped_column(String)
    teacher: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=shanghai_now
    )

    # 关系：删除课程 → 级联删除时间块 / 知识点（复习计划随知识点级联）
    sessions: Mapped[list["CourseSession"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(back_populates="course")

    def __repr__(self) -> str:
        return f"<Course id={self.id} name={self.name!r} tier={self.tier!r}>"


class CourseSession(Base):
    """课程时间块（每周重复）：day_of_week 0=周一，时间为 'HH:MM' 文本。"""

    __tablename__ = "course_sessions"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_sessions_day_of_week"),
        UniqueConstraint("course_id", "day_of_week", "start_time", name="uq_sessions_course_day_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[str] = mapped_column(String, nullable=False)  # '08:00'
    end_time: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str | None] = mapped_column(String)
    # 生效周次区间（'YYYY-MM-DD'，闭区间）；为空表示整学期有效。
    # 用于前后半学期同星期同时段的不同课程（如机械原理Ⅱ/航空航天材料工程）
    # 在 ICS 中通过 RRULE 的 COUNT/UNTIL 推导，落库后由 generate_plan 按目标日期过滤。
    starts_on: Mapped[str | None] = mapped_column(String, nullable=True)
    ends_on: Mapped[str | None] = mapped_column(String, nullable=True)
    # B/C 档课程：该时段是否释放给其他任务（0/1）
    release_slot: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    course: Mapped["Course"] = relationship(back_populates="sessions")

    def __repr__(self) -> str:
        return f"<CourseSession id={self.id} course_id={self.course_id} dow={self.day_of_week} {self.start_time}-{self.end_time}>"
