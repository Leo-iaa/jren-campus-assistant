"""数据源绑定。

对应 docs/database.md 3.9 ``data_sources``。
"""
from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, shanghai_now

# 支持的数据源类型（新数据源 = 新增 MCP adapter）
SOURCE_TYPES = ("notion", "obsidian", "ical", "caldav", "coros")


class DataSource(Base):
    """数据源绑定：Notion OAuth / Obsidian vault / iCal / CalDAV / COROS。"""

    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN ({','.join(repr(t) for t in SOURCE_TYPES)})",
            name="ck_ds_source_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    config: Mapped[str | None] = mapped_column(String)  # JSON：OAuth token / vault 路径 / URL
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last_sync_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(
        String, nullable=False, default=shanghai_now
    )

    def __repr__(self) -> str:
        return f"<DataSource id={self.id} type={self.source_type!r} name={self.name!r}>"
