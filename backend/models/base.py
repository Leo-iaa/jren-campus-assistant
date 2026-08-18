"""声明式基类：所有 ORM 模型继承自此。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import DeclarativeBase

#: 全局统一时区（对齐 docs/vision.md 时间轴：Asia/Shanghai）
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> str:
    """上海时区当前时间（'YYYY-MM-DD HH:MM:SS'）。

    作为 created_at 等时间字段的默认值，与 confirmed_at / completed_at /
    last_sync_at（均 Asia/Shanghai）保持一致，避免 SQLite datetime('now')
    混用 UTC 造成的 +8 小时偏差。
    """
    return datetime.now(_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")


class Base(DeclarativeBase):
    """项目统一的 ORM 基类。"""
