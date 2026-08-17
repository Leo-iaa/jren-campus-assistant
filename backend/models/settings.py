"""全局配置键值表（单用户，不建 users 表）。

对应 docs/database.md 3.1 ``settings``。
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class Setting(Base):
    """全局配置项，如 review_daily_cap / llm_provider。"""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)

    def __repr__(self) -> str:
        return f"<Setting key={self.key!r}>"
