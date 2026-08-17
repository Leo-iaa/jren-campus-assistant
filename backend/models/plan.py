"""日程计划项与计划版本快照。

对应 docs/database.md 3.7 ``plan_items`` 与 3.11 ``plan_versions``。
"""
from sqlalchemy import CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class PlanItem(Base):
    """日程计划项（核心表）：多态引用课程块/任务/复习/杂项，冗余 title 便于展示。

    ``UNIQUE(date, start_time)`` 是时间冲突的数据库层兜底。
    """

    __tablename__ = "plan_items"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('course','task','review','misc')", name="ck_plan_item_type"
        ),
        CheckConstraint(
            "status IN ('draft','confirmed','done','skipped','adjusted')",
            name="ck_plan_item_status",
        ),
        UniqueConstraint("date", "start_time", name="uq_plan_date_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(String, nullable=False)  # 'YYYY-MM-DD'
    start_time: Mapped[str] = mapped_column(String, nullable=False)
    end_time: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[str] = mapped_column(String, nullable=False)  # course/task/review/misc
    ref_id: Mapped[int | None] = mapped_column(Integer)  # 对应各来源表的 id
    title: Mapped[str] = mapped_column(String, nullable=False)  # 冗余标题
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="draft", server_default="draft"
    )

    def __repr__(self) -> str:
        return f"<PlanItem id={self.id} date={self.date} {self.start_time}-{self.end_time} {self.item_type}:{self.ref_id}>"


class PlanVersion(Base):
    """每日计划确认快照（版本化）：payload 存计划 JSON。"""

    __tablename__ = "plan_versions"
    __table_args__ = (
        UniqueConstraint("date", "version", name="uq_plan_versions_date_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(String, nullable=False)  # 'YYYY-MM-DD'
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # 计划 JSON 快照
    confirmed_at: Mapped[str | None] = mapped_column(String)

    def __repr__(self) -> str:
        return f"<PlanVersion id={self.id} date={self.date} v{self.version}>"
