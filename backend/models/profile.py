"""用户画像：手动偏好 + 自动学习特征 + 行为痕迹事件。

对应 docs/database.md 3.12 ``user_profile`` 与 3.13 ``profile_events``。

- ``user_profile``：一条一行画像特征（feature_key 唯一）。手动偏好（rhythm /
  no_brain_after / fixed_activities）与自动学习特征（prefer_bucket.<课程> /
  fit_bucket.<课程> / late_worker）同表存储，学习特征带 confidence（观察次数）
  与 evidence（中文证据，可解释「为什么这么排」）。
- ``profile_events``：行为痕迹明细（调整 / 完成 / 新增任务），是学习规则的
  素材与审计依据——画像证据可随时从明细重算。
"""
from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, shanghai_now


class UserProfile(Base):
    """用户画像特征条目（feature_key 唯一）。"""

    __tablename__ = "user_profile"
    __table_args__ = (
        CheckConstraint(
            "source IN ('learned','manual')", name="ck_user_profile_source"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    feature_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # 特征类型：manual（手动偏好）/ prefer_bucket / fit_bucket / late_worker
    feature_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)  # 如 'evening' / '21:00' / JSON
    confidence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )  # 学习特征：观察次数；手动条目恒 0
    evidence: Mapped[str | None] = mapped_column(Text)  # 中文可解释来源
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="learned", server_default="learned"
    )
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=shanghai_now
    )

    def __repr__(self) -> str:
        return f"<UserProfile key={self.feature_key} value={self.value!r} conf={self.confidence}>"


class ProfileEvent(Base):
    """用户行为痕迹：调整计划 / 标记完成 / 新增任务。"""

    __tablename__ = "profile_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('adjust','done','add_task')", name="ck_profile_event_type"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[str] = mapped_column(Text, nullable=False, default=shanghai_now)
    plan_date: Mapped[str | None] = mapped_column(String)  # 计划日期 YYYY-MM-DD
    subject: Mapped[str] = mapped_column(String, nullable=False)  # 学习对象键（课程名/标题）
    item_type: Mapped[str] = mapped_column(String, nullable=False)  # task/review/misc
    from_bucket: Mapped[str | None] = mapped_column(String)  # 调整前时段（仅 adjust）
    to_bucket: Mapped[str | None] = mapped_column(String)  # 调整后 / 完成 / 插入时段
    start_time: Mapped[str | None] = mapped_column(String)  # 最终开始时间 HH:MM
    title: Mapped[str | None] = mapped_column(String)  # 冗余标题（证据展示用）

    def __repr__(self) -> str:
        return f"<ProfileEvent id={self.id} {self.event_type} subject={self.subject!r} to={self.to_bucket}>"
