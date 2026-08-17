"""知识点与复习计划。

对应 docs/database.md 3.4 ``knowledge_points`` 与 3.5 ``review_schedules``。
"""
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.models.base import Base


class KnowledgePoint(Base):
    """知识点（从课堂笔记提取）：难度 1-5，关联来源笔记路径。"""

    __tablename__ = "knowledge_points"
    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="ck_kp_difficulty"),
        CheckConstraint("status IN ('active','archived')", name="ck_kp_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    content_snapshot: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    source_path: Mapped[str | None] = mapped_column(String)  # Obsidian 笔记路径
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=func.datetime("now")
    )

    course: Mapped["Course"] = relationship(back_populates="knowledge_points")
    # 删除知识点 → 级联删除其复习计划
    review_schedules: Mapped[list["ReviewSchedule"]] = relationship(
        back_populates="knowledge_point", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KnowledgePoint id={self.id} title={self.title!r} difficulty={self.difficulty}>"


class ReviewSchedule(Base):
    """复习计划：每个知识点按遗忘曲线排多条（seq 为第几次复习）。"""

    __tablename__ = "review_schedules"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','done','skipped','overdue')", name="ck_reviews_status"
        ),
        UniqueConstraint("knowledge_point_id", "seq", name="uq_reviews_kp_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 第几次复习（1,2,3...）
    due_date: Mapped[str] = mapped_column(String, nullable=False)  # 'YYYY-MM-DD'
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    completed_at: Mapped[str | None] = mapped_column(String)

    knowledge_point: Mapped["KnowledgePoint"] = relationship(back_populates="review_schedules")

    def __repr__(self) -> str:
        return f"<ReviewSchedule id={self.id} kp={self.knowledge_point_id} seq={self.seq} due={self.due_date}>"
