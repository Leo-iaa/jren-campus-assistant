"""作业任务与杂事项。

对应 docs/database.md 3.6 ``tasks`` 与 3.8 ``misc_items``。
"""
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base, shanghai_now


class Task(Base):
    """作业任务（Notion 导入 / 手动创建）。删除课程时任务保留（course_id 置 NULL）。"""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("source IN ('notion','manual')", name="ck_tasks_source"),
        CheckConstraint("status IN ('todo','doing','done','cancelled')", name="ck_tasks_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str | None] = mapped_column(String)  # 任务类型（作业/实验/考试/其他）
    description: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[str | None] = mapped_column(String)  # 截止时间
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)  # 预估耗时（供规划器）
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="manual", server_default="manual"
    )
    source_ref: Mapped[str | None] = mapped_column(String)  # Notion 页面 ID 等
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="todo", server_default="todo"
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=shanghai_now
    )

    course: Mapped["Course | None"] = relationship(back_populates="tasks")

    def __repr__(self) -> str:
        return f"<Task id={self.id} title={self.title!r} status={self.status!r}>"


class MiscItem(Base):
    """杂事项：独立表，也被 plan_items 多态引用。"""

    __tablename__ = "misc_items"
    __table_args__ = (
        CheckConstraint("status IN ('todo','done','cancelled')", name="ck_misc_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)  # 预计耗时
    preferred_time: Mapped[str | None] = mapped_column(String)  # 偏好时段（可选）
    deadline: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="todo", server_default="todo"
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=shanghai_now
    )

    def __repr__(self) -> str:
        return f"<MiscItem id={self.id} title={self.title!r}>"
