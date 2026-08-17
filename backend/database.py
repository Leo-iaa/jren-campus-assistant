"""数据库引擎与会话管理。

- 单用户起步使用 SQLite，多用户时平滑迁移 PostgreSQL（见 docs/database.md）
- SQLite 默认不强制外键，必须为每个连接打开 ``PRAGMA foreign_keys=ON``，
  否则 ON DELETE CASCADE / SET NULL 不会生效
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.models.base import Base

# SQLite 需要 check_same_thread=False（FastAPI 多线程处理请求）
_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """每个新连接打开外键约束（仅 SQLite 需要）。"""
    if _is_sqlite:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """建表（幂等）：基于 models 元数据创建所有缺失的表。"""
    Base.metadata.create_all(bind=engine)
